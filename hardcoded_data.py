import argparse
import json
import random
from datetime import datetime, timezone

from graph_utils import build_knn_edges

DEFAULT_SEED = 42
DEFAULT_MINOR_CITIES = 200
DEFAULT_NEIGHBORS = 3
MG_LAT_MIN = -22.5
MG_LAT_MAX = -14.2
MG_LNG_MIN = -51.0
MG_LNG_MAX = -39.8


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate deterministic mock graph data for Minas Gerais.")
    parser.add_argument("--output", default="mg_graph_data.json", help="Output JSON file path.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help=f"Random seed. Default: {DEFAULT_SEED}")
    parser.add_argument(
        "--minor-cities",
        type=int,
        default=DEFAULT_MINOR_CITIES,
        help=f"Number of synthetic minor cities. Default: {DEFAULT_MINOR_CITIES}",
    )
    parser.add_argument(
        "--neighbors",
        type=int,
        default=DEFAULT_NEIGHBORS,
        help=f"Number of nearest neighbors for each node. Default: {DEFAULT_NEIGHBORS}",
    )
    return parser.parse_args()


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def build_nodes(rng: random.Random, minor_cities: int) -> list[dict]:
    major_cities = [
        {"name": "Belo Horizonte", "lat": -19.9167, "lng": -43.9345, "pop": 2315560},
        {"name": "Uberlandia", "lat": -18.9113, "lng": -48.2622, "pop": 713224},
        {"name": "Contagem", "lat": -19.9316, "lng": -44.0538, "pop": 621863},
        {"name": "Juiz de Fora", "lat": -21.7583, "lng": -43.3422, "pop": 540756},
        {"name": "Betim", "lat": -19.9677, "lng": -44.1983, "pop": 411846},
        {"name": "Montes Claros", "lat": -16.7350, "lng": -43.8616, "pop": 414240},
        {"name": "Ribeirao das Neves", "lat": -19.7670, "lng": -44.0860, "pop": 329794},
        {"name": "Uberaba", "lat": -19.7470, "lng": -47.9390, "pop": 337836},
        {"name": "Governador Valadares", "lat": -18.8510, "lng": -41.9490, "pop": 257171},
        {"name": "Ipatinga", "lat": -19.4680, "lng": -42.5370, "pop": 227731},
        {"name": "Sete Lagoas", "lat": -19.4600, "lng": -44.2460, "pop": 241835},
        {"name": "Divinopolis", "lat": -20.1430, "lng": -44.8820, "pop": 231091},
        {"name": "Santa Luzia", "lat": -19.7690, "lng": -43.8510, "pop": 219134},
        {"name": "Pocos de Caldas", "lat": -21.7878, "lng": -46.5627, "pop": 163742},
        {"name": "Patos de Minas", "lat": -18.5788, "lng": -46.5180, "pop": 153585},
        {"name": "Pouso Alegre", "lat": -22.2307, "lng": -45.9316, "pop": 152549},
        {"name": "Teofilo Otoni", "lat": -17.8569, "lng": -41.5050, "pop": 140937},
        {"name": "Barbacena", "lat": -21.2258, "lng": -43.7744, "pop": 138204},
        {"name": "Varginha", "lat": -21.5544, "lng": -45.4319, "pop": 136467},
        {"name": "Conselheiro Lafaiete", "lat": -20.6588, "lng": -43.7863, "pop": 129606},
    ]

    nodes: list[dict] = []
    for index, city in enumerate(major_cities):
        population = city["pop"]
        if city["name"] == "Belo Horizonte":
            density = 7167.0
        else:
            density = population / rng.uniform(140.0, 420.0)
        area_sq_km = max(population / density, 1.0)
        nodes.append(
            {
                "id": f"MC_{index}",
                "name": city["name"],
                "lat": round(city["lat"], 6),
                "lng": round(city["lng"], 6),
                "population": population,
                "density": round(density, 6),
                "area_sq_km": round(area_sq_km, 6),
            }
        )

    for index in range(max(minor_cities, 0)):
        if rng.random() < 0.7:
            center = rng.choice(major_cities)
            lat = center["lat"] + rng.uniform(-1.5, 1.5)
            lng = center["lng"] + rng.uniform(-1.5, 1.5)
        else:
            lat = rng.uniform(MG_LAT_MIN, MG_LAT_MAX)
            lng = rng.uniform(MG_LNG_MIN, MG_LNG_MAX)

        lat = clamp(lat, MG_LAT_MIN, MG_LAT_MAX)
        lng = clamp(lng, MG_LNG_MIN, MG_LNG_MAX)
        population = rng.randint(2000, 85000)
        density = population / rng.uniform(80.0, 650.0)
        area_sq_km = max(population / density, 1.0)

        nodes.append(
            {
                "id": f"MN_{index}",
                "name": f"Cidade Simulada {index}",
                "lat": round(lat, 6),
                "lng": round(lng, 6),
                "population": population,
                "density": round(density, 6),
                "area_sq_km": round(area_sq_km, 6),
            }
        )

    nodes.sort(key=lambda node: node["id"])
    return nodes


def main() -> int:
    args = parse_args()
    rng = random.Random(args.seed)
    neighbors = max(args.neighbors, 1)

    print("Generating deterministic mock data for Minas Gerais...")
    nodes = build_nodes(rng, args.minor_cities)
    print(f"Nodes generated: {len(nodes)}")

    print(f"Building edges with {neighbors} nearest neighbors...")
    edges = build_knn_edges(nodes, k_neighbors=neighbors)
    edges.sort(key=lambda edge: edge["id"])

    output = {
        "metadata": {
            "generator": "hardcoded_data.py",
            "seed": args.seed,
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
