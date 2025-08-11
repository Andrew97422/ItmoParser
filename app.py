from flask import Flask, render_template, request
from bs4 import BeautifulSoup
import requests
from dataclasses import dataclass
from typing import List, Optional, Set, Dict
import time
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=2)

def parse_and_cache(url):
    try:
        applicants = parse_itmo_rating(url)
        app_data['cached_applicants'][url] = {'ts': time.time(), 'data': applicants}
    except Exception as e:
        print(f"Ошибка парсинга url={url}: {e}")

def get_applicants_with_cache(url):
    now = time.time()
    entry = app_data['cached_applicants'].get(url)
    if entry and now - entry['ts'] < CACHE_TTL:
        return entry['data']
    if entry:
        executor.submit(parse_and_cache, url)
        return entry['data']
    data = parse_itmo_rating(url)
    app_data['cached_applicants'][url] = {'ts': now, 'data': data}
    return data


app = Flask(__name__)

# Хранилище данных в памяти
app_data = {
    'exam_types': set(),
    'last_url': None,
    'cached_applicants': {}
}

CACHE_TTL = 5 * 60


@dataclass
class Applicant:
    position: int
    application_id: str
    exam_type: str
    exam_id: int
    exam_score: float
    total_score: float
    average_score: float
    priority: int
    ovp: bool
    vpp: bool
    consent: bool
    filtered_position: int = 0


def get_unique_exam_types(applicants: List[Applicant]) -> Set[str]:
    """Получаем уникальные виды испытаний из списка абитуриентов"""
    return {app.exam_type for app in applicants if app.exam_type.strip()}


def filter_applicants(
        applicants: List[Applicant],
        ovp: Optional[bool] = None,
        vpp: Optional[bool] = None,
        consent: Optional[bool] = None,
        search_id: Optional[str] = None,
        exam_type: Optional[str] = None,
        stats_id: Optional[str] = None,
        average_score_op: Optional[str] = None,
        average_score_val: Optional[str] = None,
        exam_score_op: Optional[str] = None,
        exam_score_val: Optional[str] = None,
        total_score_op: Optional[str] = None,
        total_score_val: Optional[str] = None,
        priority_min: Optional[int] = None,
        priority_max: Optional[int] = None
) -> Dict:
    filtered = applicants

    def cmp(value, op, ref):
        if op == 'ge':
            return value >= ref
        if op == 'g':
            return value > ref
        if op == 'le':
            return value <= ref
        if op == 'l':
            return value < ref
        if op == 'eq':
            return value == ref
        return True

    # ОВП, ВПП, согласие
    if ovp is not None:
        filtered = [a for a in filtered if a.ovp == ovp]
    if vpp is not None:
        filtered = [a for a in filtered if a.vpp == vpp]
    if consent is not None:
        filtered = [a for a in filtered if a.consent == consent]
    if search_id and search_id.strip():
        filtered = [a for a in filtered if search_id.strip().lower() in a.application_id.lower()]
    if exam_type and exam_type != 'Все' and exam_type.strip():
        if exam_type == "БВИ":
            filtered = [a for a in filtered if a.exam_type != "ВЭ"]
        else:
            filtered = [a for a in filtered if a.exam_type == exam_type]

    priority_min, priority_max = min(priority_min, priority_max), max(priority_min, priority_max)

    if priority_min is not None:
        filtered = [a for a in filtered if a.priority >= priority_min]
    if priority_max is not None:
        filtered = [a for a in filtered if a.priority <= priority_max]

    if average_score_op and average_score_val:
        try:
            val = float(average_score_val)
            filtered = [a for a in filtered if cmp(a.average_score, average_score_op, val)]
        except Exception:
            pass

    if exam_score_op and exam_score_val:
        try:
            val = float(exam_score_val)
            filtered = [a for a in filtered if cmp(a.exam_score, exam_score_op, val)]
        except Exception:
            pass

    if total_score_op and total_score_val:
        try:
            val = float(total_score_val)
            filtered = [a for a in filtered if cmp(a.total_score, total_score_op, val)]
        except Exception:
            pass

    # Сортируем по позиции
    filtered_sorted = sorted(filtered, key=lambda x: x.position)
    for idx, app in enumerate(filtered_sorted, 1):
        app.filtered_position = idx

    # Если задан номер для анализа
    stats = {}
    stats_list = []
    if stats_id and stats_id.strip():
        stats_id = stats_id.strip()
        # Найдём себя
        idx_myself = next((i for i, a in enumerate(filtered_sorted) if a.application_id == stats_id), None)
        if idx_myself is not None:
            before_me = filtered_sorted[:idx_myself]
            stats = {
                "total_before_me": len(before_me),
                "bvi_before": len([a for a in before_me if a.exam_type != "ВЭ"]),
                "ovp_before": len([a for a in before_me if a.ovp]),
                "consent_before": len([a for a in before_me if a.consent]),
                "my_row": filtered_sorted[idx_myself]
            }
            stats_list = before_me
        else:
            stats = {"not_found": True}

    return {
        'applicants': filtered_sorted,
        'total_count': len(applicants),
        'filtered_count': len(filtered),
        'stats': stats,
        'stats_list': stats_list
    }



def parse_itmo_rating(url: str) -> List[Applicant]:
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        cards = soup.select('.RatingPage_table__item__qMY0F')

        applicants = []
        for card in cards:
            try:
                position_block = card.select_one('.RatingPage_table__position__uYWvi')
                position = int(position_block.contents[0].strip())
                application_id = position_block.find('span').text.strip()
                exam_type = card.select_one('p:-soup-contains("Вид испытания:") span:nth-of-type(1)').text.strip()

                applicants.append(Applicant(
                    position=position,
                    application_id=application_id,
                    exam_type=exam_type,
                    exam_id=int(card.select_one('p:-soup-contains("ИД:") span').text),
                    exam_score=float(card.select_one('p:-soup-contains("Балл ВИ:") span').text),
                    total_score=float(card.select_one('p:-soup-contains("Балл ВИ+ИД:") span').text),
                    average_score=float(card.select_one('p:-soup-contains("Средний балл:") span').text),
                    priority=int(card.select_one('p:-soup-contains("Приоритет:") span').text),
                    ovp=card.select_one(
                        'p:-soup-contains("Основной высший приоритет:") span').text.strip().lower() == 'да',
                    vpp=card.select_one(
                        'p:-soup-contains("Высший проходной приоритет:") span').text.strip().lower() == 'да',
                    consent=card.select_one('p:-soup-contains("Есть согласие:") span').text.strip().lower() == 'да'
                ))
            except Exception as e:
                print(f"Ошибка парсинга карточки: {e}")
                continue

        return applicants
    except Exception as e:
        raise Exception(f"Ошибка парсинга: {str(e)}")


@app.route('/', methods=['GET', 'POST'])
def index():
    default_url = "https://abit.itmo.ru/rating/master/budget/2225"

    result = {
        'applicants': [],
        'total_count': 0,
        'filtered_count': 0
    }
    error = None
    filters = {
        'ovp': None,
        'vpp': None,
        'consent': None,
        'search_id': '',
        'exam_type': 'Все',
        'url': default_url
    }

    if request.method == 'POST':
        def parse_tri_state(value):
            return None if value == 'any' else value == 'yes'

        priority_min = request.form.get('priority_min')
        priority_max = request.form.get('priority_max')

        try:
            priority_min = int(priority_min) if priority_min else None
        except Exception:
            priority_min = None

        try:
            priority_max = int(priority_max) if priority_max else None
        except Exception:
            priority_max = None

        filters = {
            'ovp': parse_tri_state(request.form.get('ovp', 'any')),
            'vpp': parse_tri_state(request.form.get('vpp', 'any')),
            'consent': parse_tri_state(request.form.get('consent', 'any')),
            'search_id': request.form.get('search_id', '').strip(),
            'exam_type': request.form.get('exam_type', 'Все'),
            'url': request.form.get('url', default_url),
            'stats_id': request.form.get('stats_id', '').strip(),

            'average_score_op': request.form.get('average_score_op', ''),
            'average_score_val': request.form.get('average_score_val', ''),
            'exam_score_op': request.form.get('exam_score_op', ''),
            'exam_score_val': request.form.get('exam_score_val', ''),
            'total_score_op': request.form.get('total_score_op', ''),
            'total_score_val': request.form.get('total_score_val', ''),

            'priority_min': priority_min,
            'priority_max': priority_max,
        }

        try:
            if filters['url'] != app_data['last_url']:
                applicants = get_applicants_with_cache(filters['url'])
                app_data['exam_types'] = get_unique_exam_types(applicants)
                app_data['last_url'] = filters['url']
            else:
                applicants = get_applicants_with_cache(filters['url'])

            result = filter_applicants(
                applicants,
                ovp=filters['ovp'],
                vpp=filters['vpp'],
                consent=filters['consent'],
                search_id=filters['search_id'],
                exam_type=filters['exam_type'],
                stats_id=filters['stats_id'],
                average_score_op=filters.get('average_score_op'),
                average_score_val=filters.get('average_score_val'),
                exam_score_op=filters.get('exam_score_op'),
                exam_score_val=filters.get('exam_score_val'),
                total_score_op=filters.get('total_score_op'),
                total_score_val=filters.get('total_score_val'),
                priority_min=priority_min,
                priority_max=priority_max,
            )

        except Exception as e:
            error = str(e)
    else:
        # При первом открытии загружаем данные только если их нет
        if not app_data['exam_types'] or len(app_data['exam_types']) == 0:
            try:
                applicants = get_applicants_with_cache(filters['url'])
                app_data['exam_types'] = get_unique_exam_types(applicants)
                app_data['last_url'] = default_url
            except Exception as e:
                error = str(e)

    return render_template(
        'index.html',
        applicants=result['applicants'],
        exam_types=sorted(app_data['exam_types']),
        error=error,
        filters=filters,
        total_count=result['total_count'],
        filtered_count=result['filtered_count'],
        stats=result.get('stats', {}),
        stats_list=result.get('stats_list', [])
    )


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
