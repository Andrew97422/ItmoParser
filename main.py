import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Applicant:
    position: int  # Позиция в рейтинге
    application_id: str  # Номер заявления
    exam_type: str  # Вид испытания
    exam_id: int  # ИД
    exam_score: float  # Балл ВИ
    total_score: float  # Балл ВИ + ИД
    average_score: float  # Средний балл
    priority: int  # Приоритет
    ovp: bool  # Основной высший приоритет (ОВП)
    vpp: bool  # Высший проходной приоритет (ВПП)
    consent: bool  # Наличие согласия


def filter_applicants(
        applicants: List[Applicant],
        ovp: Optional[bool] = None,
        vpp: Optional[bool] = None,
        consent: Optional[bool] = None
) -> List[Applicant]:
    """
    Фильтрация абитуриентов по критериям ОВП, ВПП и согласию.
    Возвращает список, отсортированный по возрастанию позиции.
    """
    filtered = applicants

    if ovp is not None:
        filtered = [a for a in filtered if a.ovp == ovp]

    if vpp is not None:
        filtered = [a for a in filtered if a.vpp == vpp]

    if consent is not None:
        filtered = [a for a in filtered if a.consent == consent]

    # Сортировка по позиции (уже должна быть, но для надежности)
    return sorted(filtered, key=lambda x: x.position)


def parse_applicant_card(card) -> Applicant:
    # Позиция и номер заявления
    position_block = card.select_one('.RatingPage_table__position__uYWvi')
    position = int(position_block.contents[0].strip())
    application_id = position_block.find('span').text.strip()

    # Приоритет
    priority = int(card.select_one('p:-soup-contains("Приоритет:") span').text)

    # Вид испытания
    exam_type = card.select_one('p:-soup-contains("Вид испытания:") span:nth-of-type(1)').text.strip()

    # Баллы
    exam_id = int(card.select_one('p:-soup-contains("ИД:") span').text)
    exam_score = float(card.select_one('p:-soup-contains("Балл ВИ:") span').text)
    total_score = float(card.select_one('p:-soup-contains("Балл ВИ+ИД:") span').text)

    # Средний балл
    avg_score_span = card.select_one('p:-soup-contains("Средний балл:") span')
    average_score = float(avg_score_span.text) if avg_score_span else 0.0

    # Приоритеты (ОВП и ВПП)
    ovp_text = card.select_one('p:-soup-contains("Основной высший приоритет:") span').text.strip().lower()
    vpp_text = card.select_one('p:-soup-contains("Высший проходной приоритет:") span').text.strip().lower()

    # Согласие
    consent_text = card.select_one('p:-soup-contains("Есть согласие:") span').text.strip().lower()

    return Applicant(
        position=position,
        application_id=application_id,
        exam_type=exam_type,
        exam_id=exam_id,
        exam_score=exam_score,
        total_score=total_score,
        average_score=average_score,
        priority=priority,
        ovp=ovp_text == 'да',
        vpp=vpp_text == 'да',
        consent=consent_text == 'да'
    )


def parse_itmo_rating(
        url: str,
        ovp_filter: Optional[bool] = None,
        vpp_filter: Optional[bool] = None,
        consent_filter: Optional[bool] = None
) -> List[Applicant]:
    """
    Основная функция парсинга с возможностью фильтрации
    """
    try:
        response = requests.get(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        cards = soup.select('.RatingPage_table__item__qMY0F')

        if not cards:
            raise ValueError("Карточки абитуриентов не найдены на странице")

        applicants = [parse_applicant_card(card) for card in cards]

        # Применяем фильтрацию, если заданы параметры
        if any([ovp_filter is not None, vpp_filter is not None, consent_filter is not None]):
            applicants = filter_applicants(
                applicants,
                ovp=ovp_filter,
                vpp=vpp_filter,
                consent=consent_filter
            )

        return applicants

    except Exception as e:
        raise Exception(f"Ошибка парсинга: {str(e)}")


# Пример использования с фильтрацией
if __name__ == "__main__":
    url = "https://abit.itmo.ru/rating/master/budget/2225"
    try:
        # Пример 1: Все абитуриенты с ОВП
        print("\nВсе абитуриенты с ОВП:")
        ovp_applicants = parse_itmo_rating(url, ovp_filter=True)
        for app in ovp_applicants[:5]:  # Выводим первые 5
            print(f"{app.position}. {app.application_id} - ОВП: Да, ВПП: {'Да' if app.vpp else 'Нет'}")

        # Пример 2: Абитуриенты с ВПП и согласием
        print("\nАбитуриенты с ВПП и согласием:")
        vpp_consent_applicants = parse_itmo_rating(url, vpp_filter=True, consent_filter=True)
        for app in vpp_consent_applicants[:5]:
            print(f"{app.position}. {app.application_id} - ВПП: Да, Согласие: Да")

    except Exception as e:
        print(f"Ошибка: {e}")