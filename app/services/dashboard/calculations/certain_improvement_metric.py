def calculate_certain_improvement_metrics(
    improvements,
    history,
    settings,
) -> dict:
    result = {}
    for item in improvements:
        code = item["metricCode"]
        periods = []
        for _, payload in reversed(history):
            week = payload.get("week")
            if not week or not week.get("completed"):
                continue
            periods.append(
                {
                    "periodStart": week["periodStart"],
                    "periodEnd": week["periodEnd"],
                    "percent": int(week.get("metrics", {}).get(code, 0)),
                }
            )
            if len(periods) >= settings.certain_improvement_periods_limit:
                break
        communications = []
        for _, payload in reversed(history):
            violations = (
                payload["daily"]
                .get("metrics", {})
                .get(code, {})
                .get("violations", [])
            )
            communications.extend(reversed(violations))
            if len(communications) >= settings.certain_improvement_communications_limit:
                break
        communication_items = []
        for communication in communications[
            : settings.certain_improvement_communications_limit
        ]:
            communication_items.append(
                {
                    "callId": communication["callId"],
                    "type": communication["type"],
                    "clientEpk": communication["clientEpk"],
                    "clientFio": communication.get("clientFio") or "",
                    "clientFioEncrypted": communication.get("clientFioEncrypted", False),
                    "occurredAt": communication["occurredAt"],
                }
            )
        result[code] = {
            "metricCode": code,
            "title": item["title"],
            "recommendation": item["recommendation"],
            "severity": item["severity"],
            "periods": periods,
            "communications": communication_items,
        }
    return result
