def calculate_strengths(cards: list[dict], settings) -> list[dict]:
    result = []
    for card in cards:
        if card["positive1"] < settings.strength_min_percent:
            continue
        if card["sampleTotal"] < settings.strengths_min_sample_size:
            continue
        if card["metricCode"] in settings.strengths_excluded_metric_codes:
            continue
        result.append(
            {
                "metricCode": card["metricCode"],
                "title": card["title_positive"],
                "percent1": card["positive1"],
                "percent2": card["positive2"],
                "delta": f"{card['positive1'] - card['positive2']:+}",
                "_rating": card["strengthRating"],
            }
        )
    result.sort(key=lambda item: (-item["_rating"], item["metricCode"]))
    for item in result:
        item.pop("_rating")
    return result[: settings.strengths_limit]
