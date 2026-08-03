import sys
from collections import Counter

from arbox_client import fetch_arbox_users, load_arbox_api_key

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# סקריפט חד-פעמי (מריצים ידנית): מציג את כל ה-location_id שחוזרים מ-Arbox יחד עם שם לקוח לדוגמה,
# כדי לזהות איזה location_id שייך לאיזה סניף - ואז למלא את זה ב-arbox_location_map.json


def main():
    api_key = load_arbox_api_key()
    if not api_key:
        print("No Arbox API key found. Fill in the real key in .arbox_api_key first.")
        sys.exit(1)

    users = fetch_arbox_users(api_key, only_clients="1", active="1")
    print(f"Fetched {len(users)} active clients from Arbox.\n")

    examples = {}
    counts = Counter()
    for user in users:
        location_id = str(user.get("location_id") or "")
        counts[location_id] += 1
        examples.setdefault(location_id, f"{user.get('first_name', '')} {user.get('last_name', '')}".strip())

    print("location_id | client count | example name")
    for location_id, count in counts.most_common():
        print(f"{location_id!r:>12} | {count:>12} | {examples[location_id]}")

    print(
        "\nOnce you know which location_id is which branch, fill in "
        "arbox_location_map.json, e.g.:\n"
        '{\n  "5": "מוצקין",\n  "8": "טירת כרמל"\n}'
    )


if __name__ == "__main__":
    main()
