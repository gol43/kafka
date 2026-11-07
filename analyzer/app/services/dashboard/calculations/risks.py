from app.services.dashboard.calculations.dashboard_history import RISK_LEVELS


def calculate_risks(client_details: dict[str, dict]) -> list[dict]:
    result = []
    for client_epk, payload in client_details.items():
        risks = payload["risks"]
        level = max(risks, key=lambda item: RISK_LEVELS.get(item["level"], 0))["level"]
        result.append(
            {
                "clientEpk": client_epk,
                "clientFio": payload.get("clientFio") or "",
                "level": level,
            }
        )
    result.sort(key=_client_sort_key)
    return result


def _client_sort_key(item: dict) -> tuple:
    client_fio = (item.get("clientFio") or "").strip()
    surname = ""
    if client_fio:
        surname = client_fio.split(maxsplit=1)[0].casefold()
    missing_fio = int(not surname)
    return (
        -RISK_LEVELS.get(item["level"], 0),
        missing_fio,
        surname,
        client_fio.casefold(),
        item["clientEpk"],
    )
