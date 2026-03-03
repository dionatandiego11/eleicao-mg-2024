import argparse
import gzip
import json
import random
import time
import unicodedata
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timezone

from graph_utils import build_knn_edges

URL_CITIES = "https://raw.githubusercontent.com/kelvins/Municipios-Brasileiros/main/json/municipios.json"
DEFAULT_SEED = 42
DEFAULT_NEIGHBORS = 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate MG graph from Kelvin's municipalities dataset.")
    parser.add_argument("--output", default="mg_graph_data.json", help="Output JSON file path.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help=f"Random seed. Default: {DEFAULT_SEED}")
    parser.add_argument(
        "--neighbors",
        type=int,
        default=DEFAULT_NEIGHBORS,
        help=f"Number of nearest neighbors for each node. Default: {DEFAULT_NEIGHBORS}",
    )
    parser.add_argument("--timeout", type=int, default=20, help="Network timeout in seconds. Default: 20")
    parser.add_argument("--retries", type=int, default=3, help="Retries per request. Default: 3")
    return parser.parse_args()


def get_json(url: str, timeout: int, retries: int) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
                declared = response.headers.get_content_charset()
                content_encoding = (response.headers.get("Content-Encoding") or "").lower()
                if "gzip" in content_encoding:
                    payload = gzip.decompress(payload)
                elif "deflate" in content_encoding:
                    payload = zlib.decompress(payload)
        except (TimeoutError, urllib.error.URLError, urllib.error.HTTPError) as error:
            last_error = error
        else:
            for encoding in [declared, "utf-8", "latin1"]:
                if not encoding:
                    continue
                try:
                    decoded = payload.decode(encoding).lstrip("\ufeff")
                    return json.loads(decoded)
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    last_error = error

        if attempt < retries:
            time.sleep(1.0 * attempt)

    raise RuntimeError(f"Failed to fetch {url}: {last_error}") from last_error


def normalize_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_only.lower().split())


def build_real_population_map() -> dict[str, int]:
    return {
        normalize_name("Belo Horizonte"): 2315560,
        normalize_name("Uberlândia"): 713224,
        normalize_name("Contagem"): 621863,
        normalize_name("Juiz de Fora"): 540756,
        normalize_name("Betim"): 411846,
        normalize_name("Montes Claros"): 414240,
        normalize_name("Ribeirão das Neves"): 329794,
        normalize_name("Uberaba"): 337836,
        normalize_name("Governador Valadares"): 257171,
        normalize_name("Ipatinga"): 227731,
        normalize_name("Sete Lagoas"): 241835,
        normalize_name("Divinópolis"): 231091,
        normalize_name("Santa Luzia"): 219134,
    }


def main() -> int:
    args = parse_args()
    rng = random.Random(args.seed)
    neighbors = max(args.neighbors, 1)

    print("Fetching Brazilian municipalities data...")
    cities_data = get_json(URL_CITIES, timeout=args.timeout, retries=args.retries)
    mg_cities = [city for city in cities_data if city.get("codigo_uf") == 31]
    print(f"Found {len(mg_cities)} municipalities in Minas Gerais.")

    real_pops = build_real_population_map()
    nodes = []

    for city in mg_cities:
        name = str(city["nome"])
        city_key = normalize_name(name)
        population = real_pops.get(city_key)

        if population is None:
            population = rng.randint(3000, 150000)
            density = population / rng.uniform(90.0, 900.0)
        else:
            density = population / rng.uniform(130.0, 450.0)

        area_sq_km = max(population / density, 1.0)
        nodes.append(
            {
                "id": str(city["codigo_ibge"]),
                "name": name,
                "lat": round(float(city["latitude"]), 6),
                "lng": round(float(city["longitude"]), 6),
                "population": int(population),
                "density": round(float(density), 6),
                "area_sq_km": round(float(area_sq_km), 6),
            }
        )

    nodes.sort(key=lambda node: node["id"])

    print(f"Building edges with {neighbors} nearest neighbors...")
    edges = build_knn_edges(nodes, k_neighbors=neighbors)
    edges.sort(key=lambda edge: edge["id"])

    output = {
        "metadata": {
            "generator": "make_mock.py",
            "seed": args.seed,
            "source": URL_CITIES,
            "neighbors_per_node": neighbors,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        },
        "nodes": nodes,
        "edges": edges,
    }

    with open(args.output, "w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False, indent=2)

    print(f"Done: saved {len(nodes)} nodes and {len(edges)} edges to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
