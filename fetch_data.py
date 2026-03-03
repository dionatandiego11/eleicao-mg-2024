import argparse
import csv
import gzip
import json
import math
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict
from typing import Dict, Iterable, List, Tuple, Any

from graph_utils import build_knn_edges

STATE_CODE_MG = 31
URL_CITIES = (
    "https://servicodados.ibge.gov.br/api/v1/localidades/estados/"
    f"{STATE_CODE_MG}/municipios"
)
URL_POPULATION_2022 = (
    "https://servicodados.ibge.gov.br/api/v3/agregados/4709/periodos/2022/"
    "variaveis/93?localidades=N6[N3[31]]"
)
URL_POPULATION_2021 = (
    "https://servicodados.ibge.gov.br/api/v3/agregados/6579/periodos/2021/"
    "variaveis/9324?localidades=N6[N3[31]]"
)
URL_GEOJSON = (
    "https://raw.githubusercontent.com/tbrugz/geodata-br/master/geojson/geojs-31-mun.json"
)

DEFAULT_POPULATION = 1000
DEFAULT_NEIGHBORS = 3
DEFAULT_ELECTION_ESTADUAL_CSV = (
    "votacao_candidato-municipio_deputado_estadual_2022_mg.csv/"
    "votacao_candidato-municipio_deputado_estadual_2022_mg.csv"
)
DEFAULT_ELECTION_FEDERAL_CSV = (
    "votacao_candidato-municipio_deputado_federal_2022_mg.csv/"
    "votacao_candidato-municipio_deputado_federal_2022_mg.csv"
)
DEFAULT_ELECTION_SENADOR_CSV = (
    "votacao_candidato-municipio_senador_2022_mg.csv/"
    "votacao_candidato-municipio_senador_2022_mg.csv"
)
DEFAULT_ELECTION_GOVERNADOR_CSV = (
    "votacao_candidato-municipio_governador_2022_mg.csv/"
    "votacao_candidato-municipio_governador_2022_mg.csv"
)
DEFAULT_ELECTION_PRESIDENTE_CSV = (
    "votacao_candidato-municipio_presidente_2022_mg.csv/"
    "votacao_candidato-municipio_presidente_2022_mg.csv"
)
CARGO_DEPUTADO_ESTADUAL = "deputado_estadual"
CARGO_DEPUTADO_FEDERAL = "deputado_federal"
CARGO_SENADOR = "senador"
CARGO_GOVERNADOR = "governador"
CARGO_PRESIDENTE = "presidente"
CARGO_CONFIG = {
    CARGO_DEPUTADO_ESTADUAL: {
        "label": "Deputado Estadual",
        "cargo_code": "7",
        "default_csv": DEFAULT_ELECTION_ESTADUAL_CSV,
        "include_candidates": False,
    },
    CARGO_DEPUTADO_FEDERAL: {
        "label": "Deputado Federal",
        "cargo_code": "6",
        "default_csv": DEFAULT_ELECTION_FEDERAL_CSV,
        "include_candidates": False,
    },
    CARGO_SENADOR: {
        "label": "Senador",
        "cargo_code": "5",
        "default_csv": DEFAULT_ELECTION_SENADOR_CSV,
        "include_candidates": True,
    },
    CARGO_GOVERNADOR: {
        "label": "Governador",
        "cargo_code": "3",
        "default_csv": DEFAULT_ELECTION_GOVERNADOR_CSV,
        "include_candidates": True,
    },
    CARGO_PRESIDENTE: {
        "label": "Presidente",
        "cargo_code": "1",
        "default_csv": DEFAULT_ELECTION_PRESIDENTE_CSV,
        "include_candidates": True,
    },
}
DEFAULT_ELECTION_TURNS = "1,2"
MUNICIPALITY_NAME_ALIASES = {
    # TSE dataset uses historical/alternate spellings for these 3 MG municipalities.
    "BARAO DE MONTE ALTO": "BARAO DO MONTE ALTO",
    "DONA EUSEBIA": "DONA EUZEBIA",
    "SAO THOME DAS LETRAS": "SAO TOME DAS LETRAS",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Minas Gerais graph data from public APIs.")
    parser.add_argument(
        "--output",
        default="mg_graph_data.json",
        help="Output JSON file path. Default: mg_graph_data.json",
    )
    parser.add_argument(
        "--output-compact",
        default="mg_graph_data.compact.json",
        help="Compact output JSON file path for production. Default: mg_graph_data.compact.json",
    )
    parser.add_argument(
        "--skip-compact",
        action="store_true",
        help="Do not generate compact output JSON.",
    )
    parser.add_argument(
        "--neighbors",
        type=int,
        default=DEFAULT_NEIGHBORS,
        help=f"Number of nearest neighbors used to build edges. Default: {DEFAULT_NEIGHBORS}",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="Network timeout in seconds. Default: 20",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Maximum retries per HTTP request. Default: 3",
    )
    parser.add_argument(
        "--election-csv",
        default=None,
        help=(
            "Deprecated alias for --election-csv-estadual. "
            "If provided, it overrides only deputado estadual CSV."
        ),
    )
    parser.add_argument(
        "--election-csv-estadual",
        default=DEFAULT_ELECTION_ESTADUAL_CSV,
        help=(
            "Path to municipal election CSV (TSE) for deputado estadual. "
            f"Default: {DEFAULT_ELECTION_ESTADUAL_CSV}"
        ),
    )
    parser.add_argument(
        "--election-csv-federal",
        default=DEFAULT_ELECTION_FEDERAL_CSV,
        help=(
            "Path to municipal election CSV (TSE) for deputado federal. "
            f"Default: {DEFAULT_ELECTION_FEDERAL_CSV}"
        ),
    )
    parser.add_argument(
        "--election-csv-senador",
        default=DEFAULT_ELECTION_SENADOR_CSV,
        help=(
            "Path to municipal election CSV (TSE) for senador. "
            f"Default: {DEFAULT_ELECTION_SENADOR_CSV}"
        ),
    )
    parser.add_argument(
        "--election-csv-governador",
        default=DEFAULT_ELECTION_GOVERNADOR_CSV,
        help=(
            "Path to municipal election CSV (TSE) for governador. "
            f"Default: {DEFAULT_ELECTION_GOVERNADOR_CSV}"
        ),
    )
    parser.add_argument(
        "--election-csv-presidente",
        default=DEFAULT_ELECTION_PRESIDENTE_CSV,
        help=(
            "Path to municipal election CSV (TSE) for presidente. "
            f"Default: {DEFAULT_ELECTION_PRESIDENTE_CSV}"
        ),
    )
    parser.add_argument(
        "--election-year",
        type=int,
        default=2022,
        help="Election year for CSV filter. Default: 2022",
    )
    parser.add_argument(
        "--election-turn",
        type=int,
        default=None,
        help="Deprecated single-turn filter. If provided, overrides --election-turns.",
    )
    parser.add_argument(
        "--election-turns",
        default=DEFAULT_ELECTION_TURNS,
        help=f"Comma-separated election turns to load. Default: {DEFAULT_ELECTION_TURNS}",
    )
    parser.add_argument(
        "--skip-election",
        action="store_true",
        help="Do not load election CSV enrichment.",
    )
    return parser.parse_args()


def get_json(url: str, timeout: int = 20, retries: int = 3) -> object:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
            )
        },
    )

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
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
            decode_errors: List[Exception] = []
            tried = [declared, "utf-8", "latin1"]
            seen = set()
            for encoding in tried:
                if not encoding or encoding in seen:
                    continue
                seen.add(encoding)
                try:
                    decoded = payload.decode(encoding).lstrip("\ufeff")
                    return json.loads(decoded)
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    decode_errors.append(error)
            last_error = RuntimeError(
                f"Failed to decode JSON payload from {url}. Last decode error: {decode_errors[-1]}"
            )

        if attempt < retries:
            # Conservative backoff to reduce transient throttle/network failures.
            time.sleep(1.25 * attempt)

    raise RuntimeError(f"Request failed for {url}: {last_error}") from last_error


def parse_population(value: object, default: int = DEFAULT_POPULATION) -> int:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return max(int(value), 0)

    cleaned = str(value).strip()
    if cleaned in {"", "-", "...", "X"}:
        return default
    cleaned = cleaned.replace(".", "").replace(" ", "")
    cleaned = cleaned.replace(",", ".")
    try:
        return max(int(float(cleaned)), 0)
    except ValueError:
        return default


def normalize_municipality_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    upper = ascii_only.upper()
    clean = re.sub(r"[^A-Z0-9]+", " ", upper)
    canonical = re.sub(r"\s+", " ", clean).strip()
    return MUNICIPALITY_NAME_ALIASES.get(canonical, canonical)


def parse_int_field(value: object, default: int = 0) -> int:
    if value is None:
        return default

    cleaned = str(value).strip()
    if cleaned == "":
        return default

    cleaned = cleaned.replace(".", "").replace(" ", "")
    try:
        return int(cleaned)
    except ValueError:
        try:
            return int(float(cleaned.replace(",", ".")))
        except ValueError:
            return default


def parse_turns(turns_expr: str, single_turn: int | None = None) -> List[int]:
    if single_turn is not None:
        return [int(single_turn)]

    turns: List[int] = []
    for chunk in str(turns_expr or "").split(","):
        token = chunk.strip()
        if not token:
            continue
        try:
            value = int(token)
        except ValueError as error:
            raise ValueError(f"Invalid election turn token: {token}") from error
        if value < 1:
            raise ValueError(f"Election turn must be >= 1: {value}")
        if value not in turns:
            turns.append(value)

    if not turns:
        raise ValueError("No valid election turns provided.")
    return turns


def load_municipal_election_results(
    csv_path: str,
    year: int,
    turns: List[int],
    cargo_code: str,
    include_candidates: bool,
) -> Tuple[Dict[str, Dict[str, Dict]], Dict[str, Any]]:
    source = Path(csv_path)
    if not source.exists():
        raise FileNotFoundError(f"Election CSV not found: {source}")

    turns_set = {str(turn) for turn in turns}
    votes_by_city_turn_party: Dict[str, Dict[str, Dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(int))
    )
    total_by_city_turn: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    candidates_by_city_turn: Dict[str, Dict[str, Dict[str, Dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(dict)
    )

    parties_found: set[str] = set()
    turns_found: set[str] = set()

    rows_used = 0
    rows_used_by_turn: Dict[str, int] = defaultdict(int)
    with source.open("r", encoding="latin1", newline="") as file:
        reader = csv.DictReader(file, delimiter=";")
        for row in reader:
            if str(row.get("sg_uf", "")).strip().upper() != "MG":
                continue
            if str(row.get("cd_cargo", "")).strip() != str(cargo_code):
                continue
            if str(row.get("aa_eleicao", "")).strip() != str(year):
                continue

            turn_key = str(parse_int_field(row.get("nr_turno"), default=0))
            if turn_key not in turns_set:
                continue

            vote_type = normalize_municipality_name(row.get("nm_tipo_destinacao_votos", ""))
            if vote_type not in {"VALIDO", "VALIDOS"}:
                continue

            city_key = normalize_municipality_name(row.get("nm_municipio", ""))
            if not city_key:
                continue

            party = str(row.get("sg_partido", "")).strip().upper() or "SEM_PARTIDO"
            votes = parse_int_field(row.get("qt_votos_nom_validos"), default=0)
            if votes <= 0:
                continue

            votes_by_city_turn_party[city_key][turn_key][party] += votes
            total_by_city_turn[city_key][turn_key] += votes
            parties_found.add(party)
            turns_found.add(turn_key)
            rows_used += 1
            rows_used_by_turn[turn_key] += 1

            if include_candidates:
                candidate_id = str(row.get("sq_candidato", "")).strip()
                if not candidate_id:
                    candidate_id = str(row.get("nr_candidato", "")).strip() or f"cand_{party}"

                candidate_entry = candidates_by_city_turn[city_key][turn_key].get(candidate_id)
                if candidate_entry is None:
                    candidate_entry = {
                        "candidate_id": candidate_id,
                        "number": str(row.get("nr_candidato", "")).strip(),
                        "name": str(row.get("nm_candidato", "")).strip(),
                        "ballot_name": str(row.get("nm_urna_candidato", "")).strip(),
                        "party": party,
                        "votes": 0,
                    }
                    candidates_by_city_turn[city_key][turn_key][candidate_id] = candidate_entry
                candidate_entry["votes"] += votes

    election_by_city: Dict[str, Dict[str, Dict]] = {}
    for city_key, turn_map in total_by_city_turn.items():
        election_by_city[city_key] = {}
        for turn_key, total_votes in turn_map.items():
            party_votes_raw = votes_by_city_turn_party[city_key][turn_key]
            sorted_party_votes = sorted(party_votes_raw.items(), key=lambda item: (-item[1], item[0]))
            leader_party, leader_votes = sorted_party_votes[0]

            party_votes = {party: int(votes) for party, votes in sorted_party_votes}
            party_share_pct = {
                party: round((votes * 100.0) / total_votes, 4) for party, votes in sorted_party_votes
            }

            entry = {
                "turn": int(turn_key),
                "valid_votes_total": int(total_votes),
                "leader_party": leader_party,
                "leader_party_votes": int(leader_votes),
                "leader_party_share_pct": round((leader_votes * 100.0) / total_votes, 4),
                "party_votes": party_votes,
                "party_share_pct": party_share_pct,
            }

            if include_candidates:
                candidates_raw = list(candidates_by_city_turn[city_key][turn_key].values())
                candidates_sorted = sorted(candidates_raw, key=lambda item: (-item["votes"], item["candidate_id"]))
                candidate_votes = []
                for candidate in candidates_sorted:
                    votes = int(candidate["votes"])
                    candidate_votes.append(
                        {
                            "candidate_id": str(candidate["candidate_id"]),
                            "number": candidate["number"],
                            "name": candidate["name"],
                            "ballot_name": candidate["ballot_name"],
                            "party": candidate["party"],
                            "votes": votes,
                            "share_pct": round((votes * 100.0) / total_votes, 4),
                        }
                    )

                if candidate_votes:
                    leader_candidate = candidate_votes[0]
                    entry["leader_candidate_id"] = leader_candidate["candidate_id"]
                    entry["leader_candidate_name"] = leader_candidate["ballot_name"] or leader_candidate["name"]
                    entry["leader_candidate_votes"] = int(leader_candidate["votes"])
                    entry["leader_candidate_share_pct"] = float(leader_candidate["share_pct"])
                    entry["candidate_votes"] = candidate_votes

            election_by_city[city_key][turn_key] = entry

    stats = {
        "rows_used": rows_used,
        "rows_used_by_turn": {turn: rows_used_by_turn.get(turn, 0) for turn in sorted(turns_set)},
        "municipalities_in_csv": len(election_by_city),
        "parties_found": len(parties_found),
        "turns_found": sorted(int(turn) for turn in turns_found),
        "include_candidates": include_candidates,
    }
    return election_by_city, stats


def extract_population_map(payload: object, preferred_period: str, default: int) -> Dict[str, int]:
    population: Dict[str, int] = {}
    records = payload[0]["resultados"][0]["series"]
    for record in records:
        city_id = str(record["localidade"]["id"])
        series = record.get("serie", {})
        value = series.get(preferred_period)
        if value is None and series:
            value = next(iter(series.values()))
        population[city_id] = parse_population(value, default=default)
    return population


def compute_ring_area_and_centroid(ring: Iterable[List[float]]) -> Tuple[float, float, float]:
    pts = list(ring)
    if len(pts) < 3:
        return 0.0, 0.0, 0.0

    if pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) < 3:
        return 0.0, 0.0, 0.0

    avg_lat = sum(pt[1] for pt in pts) / len(pts)
    scale_lon = 111.320 * max(math.cos(math.radians(avg_lat)), 1e-6)
    scale_lat = 110.574

    projected = [(pt[0] * scale_lon, pt[1] * scale_lat) for pt in pts]
    area_term = 0.0
    centroid_x_term = 0.0
    centroid_y_term = 0.0

    n = len(projected)
    for i in range(n):
        x1, y1 = projected[i]
        x2, y2 = projected[(i + 1) % n]
        cross = x1 * y2 - x2 * y1
        area_term += cross
        centroid_x_term += (x1 + x2) * cross
        centroid_y_term += (y1 + y2) * cross

    signed_area = area_term / 2.0
    area = abs(signed_area)
    if area < 1e-9:
        avg_lng = sum(pt[0] for pt in pts) / len(pts)
        return 0.0, avg_lat, avg_lng

    centroid_x = centroid_x_term / (6.0 * signed_area)
    centroid_y = centroid_y_term / (6.0 * signed_area)
    centroid_lat = centroid_y / scale_lat
    centroid_lng = centroid_x / scale_lon
    return area, centroid_lat, centroid_lng


def compute_geometry_area_and_centroid(geometry: Dict) -> Tuple[float, float, float] | None:
    geom_type = geometry.get("type")
    coordinates = geometry.get("coordinates", [])
    if geom_type not in {"Polygon", "MultiPolygon"}:
        return None

    rings = []
    if geom_type == "Polygon":
        if coordinates:
            rings.append(coordinates[0])
    else:
        for polygon in coordinates:
            if polygon:
                rings.append(polygon[0])

    weighted_area = 0.0
    weighted_lat = 0.0
    weighted_lng = 0.0
    fallback_points: List[List[float]] = []

    for ring in rings:
        if not ring:
            continue
        fallback_points.extend(ring)
        area, lat, lng = compute_ring_area_and_centroid(ring)
        if area > 0:
            weighted_area += area
            weighted_lat += lat * area
            weighted_lng += lng * area

    if weighted_area > 0:
        return weighted_area, (weighted_lat / weighted_area), (weighted_lng / weighted_area)

    if fallback_points:
        avg_lat = sum(pt[1] for pt in fallback_points) / len(fallback_points)
        avg_lng = sum(pt[0] for pt in fallback_points) / len(fallback_points)
        return 0.0, avg_lat, avg_lng

    return None


def build_compact_output(full_output: Dict[str, Any]) -> Dict[str, Any]:
    compact_nodes = []
    for node in full_output.get("nodes", []):
        compact_node = {
            "id": node["id"],
            "name": node["name"],
            "lat": round(float(node["lat"]), 5),
            "lng": round(float(node["lng"]), 5),
            "area_sq_km": round(float(node.get("area_sq_km", 0.0)), 2),
        }
        election_payload = node.get("election")
        if election_payload:
            compact_election: Dict[str, Dict[str, Dict]] = {}
            for cargo_key, turns_payload in election_payload.items():
                compact_turns: Dict[str, Dict] = {}
                for turn_key, turn_data in turns_payload.items():
                    compact_turn_entry = {
                        "turn": turn_data.get("turn"),
                        "valid_votes_total": turn_data.get("valid_votes_total", 0),
                        "leader_party": turn_data.get("leader_party"),
                        "leader_party_votes": turn_data.get("leader_party_votes", 0),
                        "party_votes": turn_data.get("party_votes", {}),
                    }
                    if "candidate_votes" in turn_data:
                        compact_turn_entry["candidate_votes"] = [
                            {
                                "candidate_id": cand.get("candidate_id"),
                                "number": cand.get("number"),
                                "ballot_name": cand.get("ballot_name"),
                                "party": cand.get("party"),
                                "votes": cand.get("votes", 0),
                            }
                            for cand in turn_data.get("candidate_votes", [])
                        ]
                        compact_turn_entry["leader_candidate_id"] = turn_data.get("leader_candidate_id")
                        compact_turn_entry["leader_candidate_name"] = turn_data.get("leader_candidate_name")
                        compact_turn_entry["leader_candidate_votes"] = turn_data.get("leader_candidate_votes", 0)
                    compact_turns[str(turn_key)] = compact_turn_entry
                compact_election[cargo_key] = compact_turns
            compact_node["election"] = compact_election
        compact_nodes.append(compact_node)

    compact_edges = [
        {
            "source": edge["source"],
            "target": edge["target"],
            "distance": round(float(edge.get("distance", 0.0)), 3),
        }
        for edge in full_output.get("edges", [])
    ]

    compact_metadata = {
        "state_code": full_output.get("metadata", {}).get("state_code"),
        "neighbors_per_node": full_output.get("metadata", {}).get("neighbors_per_node"),
        "generated_at_utc": full_output.get("metadata", {}).get("generated_at_utc"),
        "election": full_output.get("metadata", {}).get("election"),
        "quality": full_output.get("metadata", {}).get("quality"),
        "is_compact": True,
    }
    return {
        "metadata": compact_metadata,
        "nodes": compact_nodes,
        "edges": compact_edges,
    }


def build_quality_metadata(
    *,
    nodes_generated: int,
    edges_generated: int,
    skipped_missing_city_name: int,
    skipped_invalid_geometry: int,
    default_population_nodes: int,
    election_stats_by_cargo: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    nodes_denominator = max(nodes_generated, 1)
    skipped_total = skipped_missing_city_name + skipped_invalid_geometry

    cargos_loaded = 0
    cargos_failed = 0
    cargos_skipped = 0
    unmatched_municipalities_by_cargo: Dict[str, int] = {}
    warnings: List[str] = []

    for cargo_key, stats in election_stats_by_cargo.items():
        status = str(stats.get("status", "not_loaded"))
        if status == "loaded":
            cargos_loaded += 1
            unmatched = int(stats.get("municipalities_unmatched", 0))
            unmatched_municipalities_by_cargo[cargo_key] = unmatched
            if unmatched > 0:
                warnings.append(
                    f"{cargo_key}: {unmatched} municipalities in CSV were not matched to nodes."
                )
        elif status == "skipped_by_flag":
            cargos_skipped += 1
        elif status in {"load_failed", "not_loaded"}:
            cargos_failed += 1

    if default_population_nodes > 0:
        warnings.append(
            f"Default population fallback was used for {default_population_nodes} municipalities."
        )
    if skipped_total > 0:
        warnings.append(f"{skipped_total} municipality features were skipped during node generation.")

    return {
        "nodes_generated": nodes_generated,
        "edges_generated": edges_generated,
        "nodes_skipped_total": skipped_total,
        "nodes_skipped_missing_city_name": skipped_missing_city_name,
        "nodes_skipped_invalid_geometry": skipped_invalid_geometry,
        "nodes_with_default_population": default_population_nodes,
        "default_population_rate_pct": round((default_population_nodes * 100.0) / nodes_denominator, 4),
        "election_cargos_loaded": cargos_loaded,
        "election_cargos_failed": cargos_failed,
        "election_cargos_skipped": cargos_skipped,
        "unmatched_municipalities_by_cargo": unmatched_municipalities_by_cargo,
        "warnings": warnings,
    }


def main() -> int:
    args = parse_args()
    neighbors = max(args.neighbors, 1)
    turns = parse_turns(args.election_turns, single_turn=args.election_turn)

    print("Fetching municipalities list for Minas Gerais...")
    cities_data = get_json(URL_CITIES, timeout=args.timeout, retries=args.retries)
    city_names = {str(city["id"]): city["nome"] for city in cities_data}
    print(f"Found {len(city_names)} municipalities.")

    print("Fetching population data from IBGE...")
    try:
        pop_payload = get_json(URL_POPULATION_2022, timeout=args.timeout, retries=args.retries)
        population_map = extract_population_map(pop_payload, preferred_period="2022", default=DEFAULT_POPULATION)
        population_source = "IBGE 2022 Census"
    except Exception as error_2022:
        print(f"2022 population data unavailable ({error_2022}). Falling back to 2021 estimates.")
        pop_payload = get_json(URL_POPULATION_2021, timeout=args.timeout, retries=args.retries)
        population_map = extract_population_map(pop_payload, preferred_period="2021", default=DEFAULT_POPULATION)
        population_source = "IBGE 2021 estimates"

    if args.election_csv:
        args.election_csv_estadual = args.election_csv

    election_csv_by_cargo = {
        CARGO_DEPUTADO_ESTADUAL: args.election_csv_estadual,
        CARGO_DEPUTADO_FEDERAL: args.election_csv_federal,
        CARGO_SENADOR: args.election_csv_senador,
        CARGO_GOVERNADOR: args.election_csv_governador,
        CARGO_PRESIDENTE: args.election_csv_presidente,
    }
    election_by_city_by_cargo: Dict[str, Dict[str, Dict[str, Dict]]] = {
        cargo_key: {} for cargo_key in CARGO_CONFIG
    }
    election_stats_by_cargo: Dict[str, Dict[str, Any]] = {}

    if args.skip_election:
        print("Election enrichment skipped by flag.")
        for cargo_key, cargo_cfg in CARGO_CONFIG.items():
            election_stats_by_cargo[cargo_key] = {
                "enabled": False,
                "status": "skipped_by_flag",
                "cargo_code": cargo_cfg["cargo_code"],
                "cargo_label": cargo_cfg["label"],
                "source_csv": election_csv_by_cargo[cargo_key],
                "year": args.election_year,
                "turns_requested": turns,
            }
    else:
        for cargo_key, cargo_cfg in CARGO_CONFIG.items():
            csv_path = election_csv_by_cargo[cargo_key]
            print(f"Loading municipal election CSV for {cargo_cfg['label']}...")
            try:
                election_by_city, loaded_stats = load_municipal_election_results(
                    csv_path=csv_path,
                    year=args.election_year,
                    turns=turns,
                    cargo_code=cargo_cfg["cargo_code"],
                    include_candidates=bool(cargo_cfg.get("include_candidates", False)),
                )
                election_by_city_by_cargo[cargo_key] = election_by_city
                election_stats_by_cargo[cargo_key] = {
                    "enabled": True,
                    "status": "loaded",
                    "cargo_code": cargo_cfg["cargo_code"],
                    "cargo_label": cargo_cfg["label"],
                    "source_csv": csv_path,
                    "year": args.election_year,
                    "turns_requested": turns,
                    "turns_found": loaded_stats["turns_found"],
                    "rows_used_by_turn": loaded_stats["rows_used_by_turn"],
                    "rows_used": loaded_stats["rows_used"],
                    "municipalities_in_csv": loaded_stats["municipalities_in_csv"],
                    "parties_found": loaded_stats["parties_found"],
                    "include_candidates": loaded_stats["include_candidates"],
                }
                print(
                    f"{cargo_cfg['label']} loaded: "
                    f"{loaded_stats['municipalities_in_csv']} municipalities, "
                    f"{loaded_stats['parties_found']} parties, turns {loaded_stats['turns_found']}."
                )
            except Exception as election_error:
                election_by_city_by_cargo[cargo_key] = {}
                election_stats_by_cargo[cargo_key] = {
                    "enabled": False,
                    "status": "load_failed",
                    "cargo_code": cargo_cfg["cargo_code"],
                    "cargo_label": cargo_cfg["label"],
                    "source_csv": csv_path,
                    "year": args.election_year,
                    "turns_requested": turns,
                    "error": str(election_error),
                }
                print(
                    f"Election enrichment unavailable for {cargo_cfg['label']} "
                    f"({election_error}). Continuing."
                )

    print("Fetching municipality geometries...")
    geo_payload = get_json(URL_GEOJSON, timeout=args.timeout, retries=args.retries)
    features = geo_payload.get("features", [])

    print("Building nodes...")
    nodes = []
    skipped_missing_city_name = 0
    skipped_invalid_geometry = 0
    default_population_nodes = 0
    matched_election_city_keys_by_cargo: Dict[str, set[str]] = {
        cargo_key: set() for cargo_key in CARGO_CONFIG
    }
    nodes_with_any_election_data = 0
    for feature in features:
        properties = feature.get("properties", {})
        geometry = feature.get("geometry", {})
        city_id = str(properties.get("id", ""))
        city_name = city_names.get(city_id)
        if not city_name:
            skipped_missing_city_name += 1
            continue

        area_centroid = compute_geometry_area_and_centroid(geometry)
        if area_centroid is None:
            skipped_invalid_geometry += 1
            continue

        area_sq_km, centroid_lat, centroid_lng = area_centroid
        population = population_map.get(city_id)
        if population is None:
            population = DEFAULT_POPULATION
            default_population_nodes += 1
        density = population / max(area_sq_km, 1.0)

        node = {
            "id": city_id,
            "name": city_name,
            "lat": round(float(centroid_lat), 6),
            "lng": round(float(centroid_lng), 6),
            "population": int(population),
            "density": round(float(density), 6),
            "area_sq_km": round(float(area_sq_km), 6),
        }

        city_key = normalize_municipality_name(city_name)
        election_payload_by_cargo: Dict[str, Dict[str, Dict]] = {}
        for cargo_key, election_by_city in election_by_city_by_cargo.items():
            turns_payload = election_by_city.get(city_key)
            if turns_payload:
                turns_sorted = sorted(turns_payload.keys(), key=lambda turn_key: int(turn_key))
                election_payload_by_cargo[cargo_key] = {turn_key: turns_payload[turn_key] for turn_key in turns_sorted}
                matched_election_city_keys_by_cargo[cargo_key].add(city_key)

        if election_payload_by_cargo:
            node["election"] = election_payload_by_cargo
            nodes_with_any_election_data += 1

        nodes.append(node)

    nodes.sort(key=lambda node: node["id"])
    skipped_total = skipped_missing_city_name + skipped_invalid_geometry
    print(f"Nodes generated: {len(nodes)} (skipped: {skipped_total}).")

    print(f"Building edges with {neighbors} nearest neighbors...")
    edges = build_knn_edges(nodes, k_neighbors=neighbors)
    edges.sort(key=lambda edge: edge["id"])

    for cargo_key, cargo_cfg in CARGO_CONFIG.items():
        election_stats = election_stats_by_cargo.get(cargo_key, {})
        if election_stats.get("status") != "loaded":
            continue

        election_by_city = election_by_city_by_cargo.get(cargo_key, {})
        matched_keys = matched_election_city_keys_by_cargo.get(cargo_key, set())
        unmatched_election_cities = len(set(election_by_city.keys()) - matched_keys)

        total_by_turn: Dict[str, int] = defaultdict(int)
        matched_by_turn: Dict[str, int] = defaultdict(int)
        for city_key, turns_payload in election_by_city.items():
            for turn_key in turns_payload.keys():
                total_by_turn[turn_key] += 1
                if city_key in matched_keys:
                    matched_by_turn[turn_key] += 1

        election_stats["municipalities_matched_in_nodes"] = len(matched_keys)
        election_stats["nodes_with_election_data"] = len(matched_keys)
        election_stats["municipalities_unmatched"] = unmatched_election_cities
        election_stats["municipalities_in_csv_by_turn"] = dict(sorted(total_by_turn.items(), key=lambda item: int(item[0])))
        election_stats["municipalities_matched_in_nodes_by_turn"] = dict(
            sorted(matched_by_turn.items(), key=lambda item: int(item[0]))
        )

        print(
            f"Election coverage on nodes ({cargo_cfg['label']}): "
            f"{len(matched_keys)}/{len(nodes)} municipalities matched."
        )
        if unmatched_election_cities > 0:
            print(
                f"Unmatched election municipalities for {cargo_cfg['label']} "
                f"(name mismatch): {unmatched_election_cities}"
            )

    status_set = {stats.get("status", "not_loaded") for stats in election_stats_by_cargo.values()}
    if status_set == {"skipped_by_flag"}:
        overall_election_status = "skipped_by_flag"
    elif status_set == {"loaded"}:
        overall_election_status = "loaded"
    elif "loaded" in status_set:
        overall_election_status = "partial"
    elif "load_failed" in status_set:
        overall_election_status = "load_failed"
    else:
        overall_election_status = "not_loaded"

    election_metadata = {
        "enabled": any(stats.get("status") == "loaded" for stats in election_stats_by_cargo.values()),
        "status": overall_election_status,
        "year": args.election_year,
        "turns_requested": turns,
        "nodes_with_any_election_data": nodes_with_any_election_data,
        "cargos": election_stats_by_cargo,
    }

    quality_metadata = build_quality_metadata(
        nodes_generated=len(nodes),
        edges_generated=len(edges),
        skipped_missing_city_name=skipped_missing_city_name,
        skipped_invalid_geometry=skipped_invalid_geometry,
        default_population_nodes=default_population_nodes,
        election_stats_by_cargo=election_stats_by_cargo,
    )

    print(
        "Data quality summary: "
        f"default population fallback in {quality_metadata['nodes_with_default_population']} municipalities; "
        f"skipped features {quality_metadata['nodes_skipped_total']}."
    )
    for warning in quality_metadata["warnings"]:
        print(f"Quality warning: {warning}")

    output = {
        "metadata": {
            "state_code": STATE_CODE_MG,
            "population_source": population_source,
            "neighbors_per_node": neighbors,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "election": election_metadata,
            "quality": quality_metadata,
        },
        "nodes": nodes,
        "edges": edges,
    }

    with open(args.output, "w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False, indent=2)
    print(f"Saved full dataset to {args.output}")

    if not args.skip_compact:
        compact_output = build_compact_output(output)
        with open(args.output_compact, "w", encoding="utf-8") as compact_file:
            json.dump(compact_output, compact_file, ensure_ascii=False, separators=(",", ":"))
        print(f"Saved compact dataset to {args.output_compact}")

    print(f"Done: saved {len(nodes)} nodes and {len(edges)} edges to {args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Fatal error: {error}", file=sys.stderr)
        raise
