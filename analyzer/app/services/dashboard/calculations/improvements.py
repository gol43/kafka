def calculate_improvements(cards: list[dict], settings) -> list[dict]:
    result = []
    for card in cards:
        if card["positive1"] >= settings.strength_min_percent:
            continue
        result.append(
            {
                "metricCode": card["metricCode"],
                "title": card["title_negative"],
                "percent1": card["negative1"],
                "percent2": card["negative2"],
                "delta": f"{card['negative1'] - card['negative2']:+}",
                "recommendation": card["recommendation"],
                "_rating": card["improvementRating"],
            }
        )
    result.sort(key=lambda item: (-item["_rating"], item["metricCode"]))
    for item in result:
        item.pop("_rating")
    return result[: settings.improvements_limit]
