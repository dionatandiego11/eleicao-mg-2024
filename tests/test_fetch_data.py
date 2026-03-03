import csv
import json
import tempfile
import unittest
from pathlib import Path

from fetch_data import (
    CARGO_CONFIG,
    build_quality_metadata,
    compute_geometry_area_and_centroid,
    load_municipal_election_results,
    normalize_municipality_name,
    parse_years,
    parse_turns,
)


class ParseTurnsTests(unittest.TestCase):
    def test_parse_turns_multi(self):
        self.assertEqual(parse_turns("1,2,2"), [1, 2])

    def test_parse_turns_single_override(self):
        self.assertEqual(parse_turns("1,2", single_turn=2), [2])

    def test_parse_turns_invalid_token(self):
        with self.assertRaises(ValueError):
            parse_turns("1,a")

    def test_parse_turns_invalid_value(self):
        with self.assertRaises(ValueError):
            parse_turns("0")


class ParseYearsTests(unittest.TestCase):
    def test_parse_years_multi(self):
        self.assertEqual(parse_years("2022,2024,2024"), [2022, 2024])

    def test_parse_years_single_override(self):
        self.assertEqual(parse_years("2022,2024", single_year=2024), [2024])

    def test_parse_years_invalid_token(self):
        with self.assertRaises(ValueError):
            parse_years("2022,abc")

    def test_parse_years_invalid_value(self):
        with self.assertRaises(ValueError):
            parse_years("1800")


class MunicipalityNormalizationTests(unittest.TestCase):
    def test_aliases(self):
        self.assertEqual(normalize_municipality_name("Dona Eusébia"), "DONA EUZEBIA")
        self.assertEqual(normalize_municipality_name("Barão de Monte Alto"), "BARAO DO MONTE ALTO")
        self.assertEqual(normalize_municipality_name("São Thomé das Letras"), "SAO TOME DAS LETRAS")

    def test_normalization_without_alias(self):
        self.assertEqual(normalize_municipality_name("Belo Horizonte"), "BELO HORIZONTE")


class ElectionCsvParserTests(unittest.TestCase):
    def test_csv_parser_with_candidates_and_turns(self):
        headers = [
            "sg_uf",
            "cd_cargo",
            "aa_eleicao",
            "nr_turno",
            "nm_tipo_destinacao_votos",
            "nm_municipio",
            "sg_partido",
            "qt_votos_nom_validos",
            "sq_candidato",
            "nr_candidato",
            "nm_candidato",
            "nm_urna_candidato",
        ]
        rows = [
            ["MG", "3", "2022", "1", "Válido", "Cidade A", "AAA", "100", "1001", "10", "Cand A1", "A1"],
            ["MG", "3", "2022", "1", "Válido", "Cidade A", "BBB", "50", "1002", "20", "Cand B1", "B1"],
            ["MG", "3", "2022", "2", "Válido", "Cidade A", "AAA", "80", "1001", "10", "Cand A1", "A1"],
            ["MG", "3", "2022", "1", "Válido", "Cidade B", "AAA", "70", "1001", "10", "Cand A1", "A1"],
            ["MG", "3", "2022", "1", "Branco", "Cidade A", "AAA", "999", "1001", "10", "Cand A1", "A1"],
            ["RJ", "3", "2022", "1", "Válido", "Cidade A", "AAA", "999", "1001", "10", "Cand A1", "A1"],
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "election.csv"
            with csv_path.open("w", encoding="latin1", newline="") as handle:
                writer = csv.writer(handle, delimiter=";")
                writer.writerow(headers)
                writer.writerows(rows)

            by_city, stats = load_municipal_election_results(
                csv_path=str(csv_path),
                year=2022,
                turns=[1, 2],
                cargo_code="3",
                include_candidates=True,
            )

        city_a = by_city["CIDADE A"]
        turn_1 = city_a["1"]
        turn_2 = city_a["2"]
        city_b_turn_1 = by_city["CIDADE B"]["1"]

        self.assertEqual(turn_1["valid_votes_total"], 150)
        self.assertEqual(turn_1["leader_party"], "AAA")
        self.assertEqual(turn_1["party_votes"]["AAA"], 100)
        self.assertEqual(turn_1["party_votes"]["BBB"], 50)
        self.assertEqual(turn_2["valid_votes_total"], 80)
        self.assertEqual(city_b_turn_1["valid_votes_total"], 70)

        self.assertIn("candidate_votes", turn_1)
        self.assertEqual(turn_1["candidate_votes"][0]["candidate_id"], "1001")
        self.assertEqual(turn_1["candidate_votes"][0]["votes"], 100)
        self.assertEqual(turn_1["leader_candidate_id"], "1001")
        self.assertEqual(turn_1["leader_candidate_name"], "A1")

        self.assertEqual(stats["rows_used"], 4)
        self.assertEqual(stats["rows_used_by_turn"]["1"], 3)
        self.assertEqual(stats["rows_used_by_turn"]["2"], 1)
        self.assertEqual(stats["municipalities_in_csv"], 2)


class QualityMetadataTests(unittest.TestCase):
    def test_quality_metadata_rollup(self):
        quality = build_quality_metadata(
            nodes_generated=10,
            edges_generated=20,
            skipped_missing_city_name=2,
            skipped_invalid_geometry=1,
            default_population_nodes=3,
            election_stats_by_cargo={
                "cargo_a": {"status": "loaded", "municipalities_unmatched": 0},
                "cargo_b": {"status": "loaded", "municipalities_unmatched": 2},
                "cargo_c": {"status": "load_failed"},
                "cargo_d": {"status": "skipped_by_flag"},
            },
        )

        self.assertEqual(quality["nodes_generated"], 10)
        self.assertEqual(quality["edges_generated"], 20)
        self.assertEqual(quality["nodes_skipped_total"], 3)
        self.assertEqual(quality["nodes_with_default_population"], 3)
        self.assertEqual(quality["default_population_rate_pct"], 30.0)
        self.assertEqual(quality["election_cargos_loaded"], 2)
        self.assertEqual(quality["election_cargos_failed"], 1)
        self.assertEqual(quality["election_cargos_skipped"], 1)
        self.assertEqual(quality["unmatched_municipalities_by_cargo"]["cargo_b"], 2)
        self.assertTrue(quality["warnings"])


class GeometryProjectionTests(unittest.TestCase):
    def test_polygon_hole_reduces_area(self):
        # Outer square with a centered inner square (hole).
        outer_ring = [
            [0.0, 0.0],
            [2.0, 0.0],
            [2.0, 2.0],
            [0.0, 2.0],
            [0.0, 0.0],
        ]
        inner_hole = [
            [0.5, 0.5],
            [1.5, 0.5],
            [1.5, 1.5],
            [0.5, 1.5],
            [0.5, 0.5],
        ]
        polygon_without_hole = {"type": "Polygon", "coordinates": [outer_ring]}
        polygon_with_hole = {"type": "Polygon", "coordinates": [outer_ring, inner_hole]}

        no_hole = compute_geometry_area_and_centroid(polygon_without_hole)
        with_hole = compute_geometry_area_and_centroid(polygon_with_hole)

        self.assertIsNotNone(no_hole)
        self.assertIsNotNone(with_hole)
        area_without_hole = float(no_hole[0])
        area_with_hole = float(with_hole[0])

        self.assertGreater(area_without_hole, 0.0)
        self.assertGreater(area_with_hole, 0.0)
        self.assertLess(area_with_hole, area_without_hole)


class CoverageTests(unittest.TestCase):
    def test_coverage_853_for_turn_1_each_cargo(self):
        output_path = Path(__file__).resolve().parents[1] / "mg_graph_data.json"
        if not output_path.exists():
            self.skipTest("mg_graph_data.json not found. Run fetch_data.py first.")

        with output_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        cargos_meta = payload.get("metadata", {}).get("election", {}).get("cargos", {})
        if not cargos_meta:
            self.fail("Election metadata not found in mg_graph_data.json")

        years_meta = payload.get("metadata", {}).get("election", {}).get("years", {})
        self.assertTrue(years_meta, "Election metadata by year not found in mg_graph_data.json")
        self.assertIn("2022", years_meta)
        self.assertIn("2024", years_meta)

        for cargo_key in CARGO_CONFIG:
            cargo_meta = cargos_meta.get(cargo_key)
            self.assertIsNotNone(cargo_meta, f"Missing metadata for cargo: {cargo_key}")
            self.assertEqual(cargo_meta.get("status"), "loaded", f"Cargo not loaded: {cargo_key}")

            matched_by_turn = cargo_meta.get("municipalities_matched_in_nodes_by_turn", {})
            self.assertTrue(matched_by_turn, f"No coverage by turn for cargo: {cargo_key}")

            turn_1_coverage = int(matched_by_turn.get("1", 0))
            self.assertEqual(
                turn_1_coverage,
                853,
                f"Coverage not 853 for cargo {cargo_key} in turn 1: got {turn_1_coverage}",
            )


if __name__ == "__main__":
    unittest.main()
