import math
import heapq
from typing import Dict, Iterable, List


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    lat1_r, lng1_r = math.radians(lat1), math.radians(lng1)
    lat2_r, lng2_r = math.radians(lat2), math.radians(lng2)
    d_lng = lng2_r - lng1_r
    d_lat = lat2_r - lat1_r

    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(d_lng / 2) ** 2
    )
    c = 2 * math.asin(math.sqrt(a))
    return 6371.0 * c


def build_knn_edges(nodes: Iterable[Dict], k_neighbors: int = 3) -> List[Dict]:
    nodes_list = list(nodes)
    if k_neighbors <= 0 or len(nodes_list) < 2:
        return []

    directed_edges: List[Dict] = []

    for i, node_a in enumerate(nodes_list):
        # Max-heap via negative distance to keep only k smallest distances.
        nearest_heap: List[tuple[float, str]] = []
        for j, node_b in enumerate(nodes_list):
            if i == j:
                continue

            distance = haversine_km(
                float(node_a["lat"]),
                float(node_a["lng"]),
                float(node_b["lat"]),
                float(node_b["lng"]),
            )
            neighbor_id = str(node_b["id"])
            if len(nearest_heap) < k_neighbors:
                heapq.heappush(nearest_heap, (-distance, neighbor_id))
            elif distance < -nearest_heap[0][0]:
                heapq.heapreplace(nearest_heap, (-distance, neighbor_id))

        source_id = str(node_a["id"])
        nearest = [(-neg_distance, neighbor_id) for neg_distance, neighbor_id in nearest_heap]
        nearest.sort(key=lambda item: item[0])
        for distance, target_id in nearest:
            edge_id = (
                f"{source_id}-{target_id}"
                if source_id <= target_id
                else f"{target_id}-{source_id}"
            )
            directed_edges.append(
                {
                    "source": source_id,
                    "target": target_id,
                    "distance": distance,
                    "id": edge_id,
                }
            )

    unique: Dict[str, Dict] = {}
    for edge in directed_edges:
        existing = unique.get(edge["id"])
        if existing is None or edge["distance"] < existing["distance"]:
            unique[edge["id"]] = edge

    return list(unique.values())
