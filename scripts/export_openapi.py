import json
from pathlib import Path

from scam2market.main import create_app


def main() -> None:
    output = Path("contracts/openapi-v1.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    schema = create_app().openapi()
    output.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {output} with {len(schema['paths'])} paths")


if __name__ == "__main__":
    main()
