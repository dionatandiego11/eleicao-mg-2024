const map = L.map('map', {
    center: [-18.5122, -44.5550],
    zoom: 6,
    zoomControl: false,
    preferCanvas: true,
});

L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 20,
}).addTo(map);

L.control.zoom({ position: 'bottomright' }).addTo(map);

const edgeGroup = L.layerGroup().addTo(map);
const nodeGroup = L.layerGroup().addTo(map);

const cityInfoEl = document.getElementById('city-info');
const infoNameEl = document.getElementById('info-name');
const infoSelectedCargoEl = document.getElementById('info-selected-cargo');
const infoSelectedTurnEl = document.getElementById('info-selected-turn');
const infoSelectedEntityTypeEl = document.getElementById('info-selected-entity-type');
const infoSelectedEntityEl = document.getElementById('info-selected-entity');
const infoSelectedValueEl = document.getElementById('info-selected-value');
const infoStateAvgValueEl = document.getElementById('info-state-avg-value');
const infoStateDeltaEl = document.getElementById('info-state-delta');
const infoValidVotesEl = document.getElementById('info-valid-votes');
const infoLeaderPartyEl = document.getElementById('info-leader-party');
const infoLeaderVotesEl = document.getElementById('info-leader-votes');
const infoLeaderCandidateEl = document.getElementById('info-leader-candidate');
const infoAreaEl = document.getElementById('info-area');

const totalCitiesEl = document.getElementById('total-cities');
const totalEdgesEl = document.getElementById('total-edges');
const statusBoxEl = document.getElementById('status-box');
const statusTextEl = document.getElementById('status-text');
const errorBoxEl = document.getElementById('error-box');
const errorTextEl = document.getElementById('error-text');
const retryBtnEl = document.getElementById('retry-btn');

const filterPanelEl = document.getElementById('filter-panel');
const cargoSelectEl = document.getElementById('cargo-select');
const turnSelectEl = document.getElementById('turn-select');
const metricSelectEl = document.getElementById('metric-select');
const entityTypeSelectEl = document.getElementById('entity-type-select');
const entitySelectEl = document.getElementById('entity-select');
const entitySummaryEl = document.getElementById('entity-summary');
const citySearchEl = document.getElementById('city-search');
const citySearchBtnEl = document.getElementById('city-search-btn');
const cityListEl = document.getElementById('city-list');
const searchHintEl = document.getElementById('search-hint');

const legendTitleEl = document.getElementById('legend-title');
const legendLowEl = document.getElementById('legend-low');
const legendMidEl = document.getElementById('legend-mid');
const legendHighEl = document.getElementById('legend-high');

const NODE_MIN_RADIUS = 0.5;
const NODE_MAX_RADIUS = 5.0;
const BASE_EDGE_STYLE = { color: '#ffffff', weight: 0.9, opacity: 0.08, smoothFactor: 1 };
const DATA_CACHE_KEY = 'mg-graph-data-cache-v1:latest';
const MAX_LOCAL_CACHE_BYTES = 4.5 * 1024 * 1024;

const CARGO_LABELS = {
    deputado_estadual: 'Deputado Estadual',
    deputado_federal: 'Deputado Federal',
    senador: 'Senador',
    governador: 'Governador',
    presidente: 'Presidente',
};

const state = {
    nodes: [],
    edges: [],
    markerByNodeId: new Map(),
    edgeLayers: [],
    nodeByNormalizedName: new Map(),
    nodeSearchEntries: [],
    nodeIndexById: new Map(),
    turnContexts: new Map(),
    selectedMarker: null,
    selectedNode: null,
    selectedCargo: null,
    selectedTurn: null,
    metricMode: 'absolute',
    entityType: 'party',
    entityKey: null,
    currentMaxMetric: 0,
    currentStateAverage: 0,
    loadedFile: null,
};

function safeNumber(value, fallback = 0) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
}

function normalizeText(value) {
    const text = String(value ?? '').trim();
    return text
        .normalize('NFKD')
        .replace(/[\u0300-\u036f]/g, '')
        .toUpperCase();
}

function normalizePartyCode(value) {
    return normalizeText(value).replace(/\s+/g, '');
}

function formatNumber(value, maximumFractionDigits = 0) {
    return new Intl.NumberFormat('pt-BR', { maximumFractionDigits }).format(value);
}

function formatPercent(value, maximumFractionDigits = 2) {
    return `${new Intl.NumberFormat('pt-BR', { maximumFractionDigits }).format(value)}%`;
}

function formatSignedPercent(value, maximumFractionDigits = 1) {
    const sign = value > 0 ? '+' : value < 0 ? '-' : '';
    return `${sign}${new Intl.NumberFormat('pt-BR', { maximumFractionDigits }).format(Math.abs(value))}%`;
}

function formatSignedNumber(value, maximumFractionDigits = 0) {
    const sign = value > 0 ? '+' : value < 0 ? '-' : '';
    return `${sign}${new Intl.NumberFormat('pt-BR', { maximumFractionDigits }).format(Math.abs(value))}`;
}

function formatCargoLabel(cargoKey) {
    if (!cargoKey) {
        return '-';
    }
    if (CARGO_LABELS[cargoKey]) {
        return CARGO_LABELS[cargoKey];
    }
    return cargoKey
        .split('_')
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(' ');
}

function formatTurnLabel(turnKey) {
    if (!turnKey) {
        return '-';
    }
    return `${turnKey}o turno`;
}

function formatEntityTypeLabel(entityType) {
    return entityType === 'candidate' ? 'Candidato' : 'Partido';
}

function formatMetric(value) {
    if (state.metricMode === 'percent') {
        return formatPercent(value, 2);
    }
    return formatNumber(value);
}

function setStatus(message, sticky = false) {
    statusTextEl.textContent = message;
    statusBoxEl.hidden = false;
    statusBoxEl.dataset.sticky = sticky ? '1' : '0';
    if (!sticky) {
        window.setTimeout(() => {
            if (statusBoxEl.dataset.sticky === '1') {
                return;
            }
            statusBoxEl.hidden = true;
        }, 2600);
    }
}

function showError(message) {
    errorTextEl.textContent = message;
    errorBoxEl.hidden = false;
    setStatus('Erro ao carregar os dados.', true);
}

function hideError() {
    errorBoxEl.hidden = true;
}

function normalizeCandidate(raw) {
    const candidateId = String(raw?.candidate_id ?? '').trim();
    if (!candidateId) {
        return null;
    }

    const number = String(raw?.number ?? '').trim();
    const ballotName = String(raw?.ballot_name ?? '').trim();
    const name = String(raw?.name ?? '').trim();
    const party = normalizePartyCode(raw?.party) || 'SEM_PARTIDO';
    const votes = Math.max(0, safeNumber(raw?.votes, 0));

    return {
        candidate_id: candidateId,
        number,
        ballot_name: ballotName,
        name,
        party,
        votes,
        label: ballotName || name || number || candidateId,
    };
}

function normalizeTurnEntry(turnKey, rawTurn) {
    if (!rawTurn || typeof rawTurn !== 'object') {
        return null;
    }

    const partyVotes = {};
    const rawPartyVotes = rawTurn.party_votes;
    if (rawPartyVotes && typeof rawPartyVotes === 'object') {
        Object.entries(rawPartyVotes).forEach(([partyCode, votes]) => {
            const normalizedParty = normalizePartyCode(partyCode);
            if (!normalizedParty) {
                return;
            }
            partyVotes[normalizedParty] = Math.max(0, safeNumber(votes, 0));
        });
    }

    if (Object.keys(partyVotes).length === 0) {
        return null;
    }

    const candidates = Array.isArray(rawTurn.candidate_votes)
        ? rawTurn.candidate_votes.map(normalizeCandidate).filter(Boolean)
        : [];
    candidates.sort((a, b) => b.votes - a.votes || a.label.localeCompare(b.label, 'pt-BR'));

    const leaderParty = normalizePartyCode(rawTurn.leader_party) || null;
    const leaderPartyVotes = Math.max(
        0,
        safeNumber(rawTurn.leader_party_votes, leaderParty ? partyVotes[leaderParty] : 0)
    );
    const leaderCandidateId = String(rawTurn.leader_candidate_id ?? '').trim() || null;
    const leaderCandidateName = String(rawTurn.leader_candidate_name ?? '').trim() || null;
    const leaderCandidateVotes = Math.max(0, safeNumber(rawTurn.leader_candidate_votes, 0));

    return {
        turn: safeNumber(rawTurn.turn, safeNumber(turnKey, 0)),
        valid_votes_total: Math.max(0, safeNumber(rawTurn.valid_votes_total, 0)),
        leader_party: leaderParty,
        leader_party_votes: leaderPartyVotes,
        leader_candidate_id: leaderCandidateId,
        leader_candidate_name: leaderCandidateName,
        leader_candidate_votes: leaderCandidateVotes,
        party_votes: partyVotes,
        candidate_votes: candidates,
    };
}

function normalizeElection(rawElection) {
    if (!rawElection || typeof rawElection !== 'object') {
        return null;
    }

    const election = {};
    Object.entries(rawElection).forEach(([cargoKey, cargoPayload]) => {
        if (!cargoPayload || typeof cargoPayload !== 'object') {
            return;
        }

        const turns = {};
        if (Object.prototype.hasOwnProperty.call(cargoPayload, 'party_votes')) {
            const normalizedTurn = normalizeTurnEntry('1', cargoPayload);
            if (normalizedTurn) {
                turns['1'] = normalizedTurn;
            }
        } else {
            Object.entries(cargoPayload).forEach(([turnKey, turnPayload]) => {
                const normalizedTurn = normalizeTurnEntry(turnKey, turnPayload);
                if (normalizedTurn) {
                    turns[String(turnKey)] = normalizedTurn;
                }
            });
        }

        if (Object.keys(turns).length > 0) {
            election[cargoKey] = turns;
        }
    });

    return Object.keys(election).length > 0 ? election : null;
}

function normalizeNode(raw) {
    const id = String(raw?.id ?? '').trim();
    const name = String(raw?.name ?? '').trim();
    const lat = safeNumber(raw?.lat, NaN);
    const lng = safeNumber(raw?.lng, NaN);
    if (!id || !name || !Number.isFinite(lat) || !Number.isFinite(lng)) {
        return null;
    }

    return {
        id,
        name,
        lat,
        lng,
        area_sq_km: Math.max(0, safeNumber(raw?.area_sq_km, 0)),
        election: normalizeElection(raw?.election),
    };
}

function normalizeEdge(raw) {
    const source = String(raw?.source ?? '').trim();
    const target = String(raw?.target ?? '').trim();
    if (!source || !target || source === target) {
        return null;
    }

    return {
        source,
        target,
        distance: Math.max(0, safeNumber(raw?.distance, 0)),
    };
}

function buildTurnContextKey(cargoKey, turnKey) {
    if (!cargoKey || !turnKey) {
        return null;
    }
    return `${cargoKey}|${String(turnKey)}`;
}

function createEntityStats({ key, label, party, number }, nodeCount) {
    return {
        key,
        label,
        party: party || 'SEM_PARTIDO',
        number: number || '',
        votesByNode: new Float64Array(nodeCount),
        totalVotes: 0,
        citiesWithVotes: 0,
        topCityIndex: -1,
        topCityVotes: 0,
        leaderCities: 0,
        percentByNode: null,
        maxPercent: 0,
        sumPercent: 0,
    };
}

function getOrCreateTurnContext(turnContexts, cargoKey, turnKey, nodeCount) {
    const key = buildTurnContextKey(cargoKey, turnKey);
    if (!key) {
        return null;
    }
    let context = turnContexts.get(key);
    if (!context) {
        context = {
            cargoKey,
            turnKey: String(turnKey),
            validVotesByNode: new Float64Array(nodeCount),
            hasTurnDataByNode: new Uint8Array(nodeCount),
            citiesWithTurnData: 0,
            totalValidVotes: 0,
            entities: {
                party: new Map(),
                candidate: new Map(),
            },
            options: {
                party: [],
                candidate: [],
            },
        };
        turnContexts.set(key, context);
    }
    return context;
}

function ensurePercentMetrics(entityStats, turnContext) {
    if (!entityStats || !turnContext || entityStats.percentByNode) {
        return;
    }

    const percentByNode = new Float64Array(state.nodes.length);
    let maxPercent = 0;
    let sumPercent = 0;

    for (let index = 0; index < state.nodes.length; index += 1) {
        const validVotes = turnContext.validVotesByNode[index];
        const votes = entityStats.votesByNode[index];
        const percent = validVotes > 0 ? (votes * 100) / validVotes : 0;
        percentByNode[index] = percent;
        sumPercent += percent;
        if (percent > maxPercent) {
            maxPercent = percent;
        }
    }

    entityStats.percentByNode = percentByNode;
    entityStats.maxPercent = maxPercent;
    entityStats.sumPercent = sumPercent;
}

function getTurnContext(cargoKey = state.selectedCargo, turnKey = state.selectedTurn) {
    const key = buildTurnContextKey(cargoKey, turnKey);
    if (!key) {
        return null;
    }
    return state.turnContexts.get(key) || null;
}

function getEntityStatsFromContext(turnContext, entityType, entityKey) {
    if (!turnContext || !entityKey) {
        return null;
    }
    const byType = entityType === 'candidate' ? turnContext.entities.candidate : turnContext.entities.party;
    return byType.get(entityKey) || null;
}

function getSelectedEntityStats() {
    const turnContext = getTurnContext();
    if (!turnContext) {
        return { turnContext: null, entityStats: null };
    }
    const entityStats = getEntityStatsFromContext(turnContext, state.entityType, state.entityKey);
    return { turnContext, entityStats };
}

function getMetricForNode(nodeId, turnContext, entityStats) {
    if (!turnContext || !entityStats) {
        return 0;
    }
    const nodeIndex = state.nodeIndexById.get(nodeId);
    if (typeof nodeIndex !== 'number') {
        return 0;
    }
    if (state.metricMode === 'percent') {
        ensurePercentMetrics(entityStats, turnContext);
        return Math.max(0, safeNumber(entityStats.percentByNode[nodeIndex], 0));
    }
    return Math.max(0, safeNumber(entityStats.votesByNode[nodeIndex], 0));
}

function buildTurnContexts(nodes) {
    const nodeCount = nodes.length;
    state.nodeIndexById = new Map();
    nodes.forEach((node, index) => {
        state.nodeIndexById.set(node.id, index);
    });

    const turnContexts = new Map();

    nodes.forEach((node, nodeIndex) => {
        Object.entries(node.election || {}).forEach(([cargoKey, cargoPayload]) => {
            Object.entries(cargoPayload || {}).forEach(([turnKey, turnData]) => {
                const context = getOrCreateTurnContext(turnContexts, cargoKey, turnKey, nodeCount);
                if (!context) {
                    return;
                }

                if (!context.hasTurnDataByNode[nodeIndex]) {
                    context.hasTurnDataByNode[nodeIndex] = 1;
                    context.citiesWithTurnData += 1;
                }

                const validVotes = Math.max(0, safeNumber(turnData.valid_votes_total, 0));
                context.validVotesByNode[nodeIndex] = validVotes;
                context.totalValidVotes += validVotes;

                Object.entries(turnData.party_votes || {}).forEach(([party, rawVotes]) => {
                    const votes = Math.max(0, safeNumber(rawVotes, 0));
                    let partyStats = context.entities.party.get(party);
                    if (!partyStats) {
                        partyStats = createEntityStats(
                            {
                                key: party,
                                label: party,
                                party,
                                number: '',
                            },
                            nodeCount
                        );
                        context.entities.party.set(party, partyStats);
                    }

                    partyStats.votesByNode[nodeIndex] = votes;
                    partyStats.totalVotes += votes;
                    if (votes > 0) {
                        partyStats.citiesWithVotes += 1;
                    }
                    if (votes > partyStats.topCityVotes) {
                        partyStats.topCityVotes = votes;
                        partyStats.topCityIndex = nodeIndex;
                    }
                });

                (turnData.candidate_votes || []).forEach((candidate) => {
                    const candidateId = String(candidate?.candidate_id || '').trim();
                    if (!candidateId) {
                        return;
                    }

                    const votes = Math.max(0, safeNumber(candidate.votes, 0));
                    let candidateStats = context.entities.candidate.get(candidateId);
                    if (!candidateStats) {
                        candidateStats = createEntityStats(
                            {
                                key: candidateId,
                                label: candidate.label || candidate.ballot_name || candidate.name || candidateId,
                                party: candidate.party || 'SEM_PARTIDO',
                                number: candidate.number || '',
                            },
                            nodeCount
                        );
                        context.entities.candidate.set(candidateId, candidateStats);
                    }

                    candidateStats.votesByNode[nodeIndex] = votes;
                    candidateStats.totalVotes += votes;
                    if (votes > 0) {
                        candidateStats.citiesWithVotes += 1;
                    }
                    if (votes > candidateStats.topCityVotes) {
                        candidateStats.topCityVotes = votes;
                        candidateStats.topCityIndex = nodeIndex;
                    }
                });

                const leaderParty = String(turnData.leader_party || '').trim();
                if (leaderParty) {
                    const leaderPartyStats = context.entities.party.get(leaderParty);
                    if (leaderPartyStats) {
                        leaderPartyStats.leaderCities += 1;
                    }
                }

                const leaderCandidateId = String(turnData.leader_candidate_id || '').trim();
                if (leaderCandidateId) {
                    const leaderCandidateStats = context.entities.candidate.get(leaderCandidateId);
                    if (leaderCandidateStats) {
                        leaderCandidateStats.leaderCities += 1;
                    }
                }
            });
        });
    });

    turnContexts.forEach((context) => {
        context.options.party = Array.from(context.entities.party.values())
            .map((entity) => ({
                key: entity.key,
                label: entity.label,
                totalVotes: entity.totalVotes,
            }))
            .sort((a, b) => b.totalVotes - a.totalVotes || a.label.localeCompare(b.label, 'pt-BR'));

        context.options.candidate = Array.from(context.entities.candidate.values())
            .map((entity) => ({
                key: entity.key,
                label: `${entity.label} (${entity.party}${entity.number ? ` ${entity.number}` : ''})`,
                totalVotes: entity.totalVotes,
            }))
            .sort((a, b) => b.totalVotes - a.totalVotes || a.label.localeCompare(b.label, 'pt-BR'));
    });

    state.turnContexts = turnContexts;
}

function readCachedPayload() {
    try {
        const serialized = window.localStorage.getItem(DATA_CACHE_KEY);
        if (!serialized) {
            return null;
        }
        const parsed = JSON.parse(serialized);
        if (!parsed || typeof parsed !== 'object' || !parsed.payload) {
            window.localStorage.removeItem(DATA_CACHE_KEY);
            return null;
        }
        return parsed;
    } catch (error) {
        console.warn('Invalid cached graph payload. Cache will be cleared.', error);
        try {
            window.localStorage.removeItem(DATA_CACHE_KEY);
        } catch (clearError) {
            console.warn('Failed to clear local cache.', clearError);
        }
        return null;
    }
}

function writeCachedPayload(path, payload) {
    try {
        const record = {
            path,
            cached_at_utc: new Date().toISOString(),
            generated_at_utc: payload?.metadata?.generated_at_utc || null,
            payload,
        };
        const serialized = JSON.stringify(record);
        if (serialized.length * 2 > MAX_LOCAL_CACHE_BYTES) {
            return;
        }
        window.localStorage.setItem(DATA_CACHE_KEY, serialized);
    } catch (error) {
        console.warn('Unable to persist graph cache locally.', error);
    }
}

function getTurnData(node, cargoKey = state.selectedCargo, turnKey = state.selectedTurn) {
    if (!node?.election || !cargoKey || !turnKey) {
        return null;
    }
    return node.election?.[cargoKey]?.[String(turnKey)] || null;
}

function getVoteRadius(metricValue, maxMetric) {
    if (maxMetric <= 0 || metricValue <= 0) {
        return NODE_MIN_RADIUS;
    }
    const ratio = Math.max(0, Math.min(1, metricValue / maxMetric));
    const eased = Math.pow(ratio, 0.52);
    return NODE_MIN_RADIUS + eased * (NODE_MAX_RADIUS - NODE_MIN_RADIUS);
}

function getVoteColor(metricValue, maxMetric) {
    if (metricValue <= 0 || maxMetric <= 0) {
        return '#2f3f56';
    }
    const ratio = Math.max(0, Math.min(1, metricValue / maxMetric));
    const eased = Math.pow(ratio, 0.82);
    return d3.interpolateYlOrRd(0.16 + eased * 0.82);
}

function getVoteFillOpacity(metricValue, maxMetric) {
    if (metricValue <= 0 || maxMetric <= 0) {
        return 0.08;
    }
    const ratio = Math.max(0, Math.min(1, metricValue / maxMetric));
    return Math.min(0.92, 0.18 + Math.pow(ratio, 0.62) * 0.72);
}

function resetMarkerStyle(marker) {
    if (!marker?._baseStyle) {
        return;
    }
    marker.setStyle(marker._baseStyle);
    marker.setRadius(marker._baseRadius || NODE_MIN_RADIUS);
}

function highlightMarker(marker) {
    marker.setStyle({
        weight: 1.7,
        color: '#ffea00',
        fillOpacity: 1,
        opacity: 1,
    });
}

function clearNodeInfo() {
    if (state.selectedMarker) {
        return;
    }
    cityInfoEl.hidden = true;
}

function getSelectedEntityLabel() {
    if (!state.entityKey) {
        return '-';
    }
    const selectedOption = entitySelectEl.options[entitySelectEl.selectedIndex];
    if (selectedOption && selectedOption.value === state.entityKey) {
        return selectedOption.textContent || state.entityKey;
    }
    return state.entityKey;
}

function showNodeInfo(node) {
    cityInfoEl.hidden = false;
    infoNameEl.textContent = node.name;
    infoAreaEl.textContent = formatNumber(node.area_sq_km, 1);
    infoSelectedCargoEl.textContent = formatCargoLabel(state.selectedCargo);
    infoSelectedTurnEl.textContent = formatTurnLabel(state.selectedTurn);
    infoSelectedEntityTypeEl.textContent = formatEntityTypeLabel(state.entityType);
    infoSelectedEntityEl.textContent = getSelectedEntityLabel();

    const turnData = getTurnData(node);
    const { turnContext, entityStats } = getSelectedEntityStats();
    if (!turnData || !state.entityKey || !turnContext || !entityStats) {
        infoSelectedValueEl.textContent = state.metricMode === 'percent' ? '0%' : '0';
        infoStateAvgValueEl.textContent = state.metricMode === 'percent' ? '0%' : '0';
        infoStateDeltaEl.textContent = '-';
        infoValidVotesEl.textContent = '0';
        infoLeaderPartyEl.textContent = '-';
        infoLeaderVotesEl.textContent = '0';
        infoLeaderCandidateEl.textContent = '-';
        return;
    }

    const cityMetric = getMetricForNode(node.id, turnContext, entityStats);
    const stateAverage = state.currentStateAverage;
    infoSelectedValueEl.textContent = formatMetric(cityMetric);
    infoStateAvgValueEl.textContent = formatMetric(stateAverage);

    if (state.metricMode === 'percent') {
        infoStateDeltaEl.textContent = formatSignedPercent(cityMetric - stateAverage, 2);
    } else if (stateAverage > 0) {
        const ratioDiff = ((cityMetric - stateAverage) / stateAverage) * 100;
        infoStateDeltaEl.textContent =
            `${formatSignedNumber(cityMetric - stateAverage)} (${formatSignedPercent(ratioDiff, 1)})`;
    } else {
        infoStateDeltaEl.textContent = formatSignedNumber(cityMetric - stateAverage);
    }

    infoValidVotesEl.textContent = formatNumber(turnData.valid_votes_total);
    infoLeaderPartyEl.textContent = turnData.leader_party || '-';
    infoLeaderVotesEl.textContent = formatNumber(turnData.leader_party_votes || 0);
    infoLeaderCandidateEl.textContent = turnData.leader_candidate_name || '-';
}

function clearSelection() {
    if (state.selectedMarker) {
        resetMarkerStyle(state.selectedMarker);
    }
    state.selectedMarker = null;
    state.selectedNode = null;
    cityInfoEl.hidden = true;
}

function focusNode(node, flyTo = false) {
    const marker = state.markerByNodeId.get(node.id);
    if (!marker) {
        return;
    }

    if (state.selectedMarker && state.selectedMarker !== marker) {
        resetMarkerStyle(state.selectedMarker);
    }
    state.selectedMarker = marker;
    state.selectedNode = node;

    marker.setRadius(marker._baseRadius || NODE_MIN_RADIUS);
    marker.setStyle(marker._baseStyle || {
        fillColor: '#2f3f56',
        color: '#ffffff',
        weight: 0.45,
        opacity: 0.72,
        fillOpacity: 0.12,
    });
    highlightMarker(marker);
    showNodeInfo(node);

    if (flyTo) {
        map.flyTo([node.lat, node.lng], Math.max(map.getZoom(), 8), { duration: 0.45 });
    }
}

function collectCargos(nodes) {
    if (state.turnContexts.size > 0) {
        const cargosFromContext = new Set();
        state.turnContexts.forEach((context) => {
            cargosFromContext.add(context.cargoKey);
        });
        if (cargosFromContext.size > 0) {
            return Array.from(cargosFromContext)
                .sort((a, b) => formatCargoLabel(a).localeCompare(formatCargoLabel(b), 'pt-BR'));
        }
    }

    const cargos = new Set();
    nodes.forEach((node) => {
        Object.keys(node.election || {}).forEach((cargoKey) => cargos.add(cargoKey));
    });
    return Array.from(cargos).sort((a, b) => formatCargoLabel(a).localeCompare(formatCargoLabel(b), 'pt-BR'));
}

function collectTurns(nodes, cargoKey) {
    if (state.turnContexts.size > 0 && cargoKey) {
        const turnsFromContext = new Set();
        state.turnContexts.forEach((context) => {
            if (context.cargoKey === cargoKey) {
                turnsFromContext.add(String(context.turnKey));
            }
        });
        if (turnsFromContext.size > 0) {
            return Array.from(turnsFromContext).sort((a, b) => Number(a) - Number(b));
        }
    }

    const turns = new Set();
    nodes.forEach((node) => {
        const cargoPayload = node.election?.[cargoKey];
        if (!cargoPayload) {
            return;
        }
        Object.keys(cargoPayload).forEach((turnKey) => turns.add(String(turnKey)));
    });
    return Array.from(turns).sort((a, b) => Number(a) - Number(b));
}

function collectParties(nodes, cargoKey, turnKey) {
    const turnContext = getTurnContext(cargoKey, turnKey);
    if (turnContext) {
        return turnContext.options.party.slice();
    }

    const totals = new Map();
    nodes.forEach((node) => {
        const turnData = getTurnData(node, cargoKey, turnKey);
        if (!turnData) {
            return;
        }
        Object.entries(turnData.party_votes || {}).forEach(([party, votes]) => {
            totals.set(party, (totals.get(party) || 0) + Math.max(0, safeNumber(votes, 0)));
        });
    });

    return Array.from(totals.entries())
        .map(([key, totalVotes]) => ({ key, label: key, totalVotes }))
        .sort((a, b) => b.totalVotes - a.totalVotes || a.label.localeCompare(b.label, 'pt-BR'));
}

function collectCandidates(nodes, cargoKey, turnKey) {
    const turnContext = getTurnContext(cargoKey, turnKey);
    if (turnContext) {
        return turnContext.options.candidate.slice();
    }

    const totals = new Map();
    nodes.forEach((node) => {
        const turnData = getTurnData(node, cargoKey, turnKey);
        if (!turnData) {
            return;
        }
        (turnData.candidate_votes || []).forEach((candidate) => {
            const key = String(candidate.candidate_id || '').trim();
            if (!key) {
                return;
            }

            const found = totals.get(key) || {
                key,
                label: candidate.label || key,
                party: candidate.party || 'SEM_PARTIDO',
                number: candidate.number || '',
                totalVotes: 0,
            };
            found.totalVotes += Math.max(0, safeNumber(candidate.votes, 0));
            if (!found.label && candidate.label) {
                found.label = candidate.label;
            }
            totals.set(key, found);
        });
    });

    return Array.from(totals.values())
        .map((candidate) => ({
            key: candidate.key,
            label: `${candidate.label} (${candidate.party}${candidate.number ? ` ${candidate.number}` : ''})`,
            totalVotes: candidate.totalVotes,
        }))
        .sort((a, b) => b.totalVotes - a.totalVotes || a.label.localeCompare(b.label, 'pt-BR'));
}

function getDefaultCargo(cargos) {
    if (cargos.includes('governador')) {
        return 'governador';
    }
    if (cargos.includes('presidente')) {
        return 'presidente';
    }
    return cargos[0] || null;
}

function getDeclutterProfile(zoom) {
    if (zoom <= 5) {
        return { edgeOpacity: 0, minRatio: 0.22 };
    }
    if (zoom <= 6) {
        return { edgeOpacity: 0, minRatio: 0.10 };
    }
    if (zoom <= 7) {
        return { edgeOpacity: 0.03, minRatio: 0.04 };
    }
    if (zoom <= 8) {
        return { edgeOpacity: 0.06, minRatio: 0.016 };
    }
    return { edgeOpacity: BASE_EDGE_STYLE.opacity, minRatio: 0 };
}

function updateLegend(maxMetric) {
    const safeMax = Math.max(0, maxMetric);
    const mid = safeMax / 2;

    legendTitleEl.textContent = state.metricMode === 'percent'
        ? '% do total de votos da cidade'
        : 'Votos brutos por cidade';
    legendLowEl.textContent = state.metricMode === 'percent' ? '0%' : '0';
    legendMidEl.textContent = state.metricMode === 'percent' ? formatPercent(mid, 1) : formatNumber(mid);
    legendHighEl.textContent = state.metricMode === 'percent' ? formatPercent(safeMax, 1) : formatNumber(safeMax);
}

function updateEntitySummary() {
    if (!state.selectedCargo || !state.selectedTurn || !state.entityKey) {
        entitySummaryEl.textContent = 'Selecione cargo, turno e entidade para ver o resumo.';
        state.currentStateAverage = 0;
        return;
    }

    const { turnContext, entityStats } = getSelectedEntityStats();
    if (!turnContext || !entityStats) {
        entitySummaryEl.textContent = 'Entidade sem dados para o recorte atual.';
        state.currentStateAverage = 0;
        return;
    }

    const totalVotes = entityStats.totalVotes;
    const topCityName = entityStats.topCityIndex >= 0
        ? state.nodes[entityStats.topCityIndex]?.name || '-'
        : '-';
    const topCityVotes = entityStats.topCityVotes;
    const citiesWithVotes = entityStats.citiesWithVotes;
    const leaderCities = entityStats.leaderCities;

    let citySimpleAverage = 0;
    let stateAverage = 0;
    if (state.metricMode === 'percent') {
        ensurePercentMetrics(entityStats, turnContext);
        citySimpleAverage = turnContext.citiesWithTurnData > 0
            ? entityStats.sumPercent / turnContext.citiesWithTurnData
            : 0;
        stateAverage = turnContext.totalValidVotes > 0
            ? (totalVotes * 100) / turnContext.totalValidVotes
            : 0;
    } else {
        citySimpleAverage = turnContext.citiesWithTurnData > 0
            ? totalVotes / turnContext.citiesWithTurnData
            : 0;
        stateAverage = citySimpleAverage;
    }
    state.currentStateAverage = stateAverage;

    const cargoLabel = formatCargoLabel(state.selectedCargo);
    const turnLabel = formatTurnLabel(state.selectedTurn);
    const entityLabel = getSelectedEntityLabel();
    const averageLabel = formatMetric(stateAverage);

    if (state.metricMode === 'percent') {
        const cityAvgLabel = formatPercent(citySimpleAverage, 2);
        entitySummaryEl.textContent =
            `${cargoLabel} (${turnLabel}) / ${entityLabel}: ${formatNumber(totalVotes)} votos no estado, ` +
            `votos em ${citiesWithVotes} cidades, lidera em ${leaderCities} cidades, ` +
            `pico em ${topCityName} (${formatNumber(topCityVotes)} votos), percentual estadual ponderado ${averageLabel} ` +
            `(media simples dos municipios: ${cityAvgLabel}).`;
        return;
    }

    entitySummaryEl.textContent =
        `${cargoLabel} (${turnLabel}) / ${entityLabel}: ${formatNumber(totalVotes)} votos no estado, ` +
        `votos em ${citiesWithVotes} cidades, lidera em ${leaderCities} cidades, ` +
        `pico em ${topCityName} (${formatNumber(topCityVotes)} votos), media por cidade ${averageLabel}.`;
}

function setMarkerInteractivity(marker, enabled) {
    if (marker?._path) {
        marker._path.style.pointerEvents = enabled ? 'auto' : 'none';
    }
}

function applyDeclutter() {
    const profile = getDeclutterProfile(map.getZoom());
    const maxMetric = state.currentMaxMetric;

    state.edgeLayers.forEach((edgeLayer) => {
        edgeLayer._baseOpacity = profile.edgeOpacity;
        edgeLayer.setStyle({
            ...BASE_EDGE_STYLE,
            opacity: profile.edgeOpacity,
        });
        if (edgeLayer._path) {
            edgeLayer._path.style.pointerEvents = profile.edgeOpacity > 0 ? 'auto' : 'none';
        }
    });

    state.nodes.forEach((node) => {
        const marker = state.markerByNodeId.get(node.id);
        if (!marker || !marker._baseStyle) {
            return;
        }

        const metric = Math.max(0, safeNumber(marker._metricValue, 0));
        const ratio = maxMetric > 0 ? metric / maxMetric : 0;
        const isSelected = state.selectedMarker === marker;
        const visible = isSelected || ratio >= profile.minRatio;

        marker._hiddenByZoom = !visible;
        if (!visible) {
            marker.setStyle({
                ...marker._baseStyle,
                opacity: 0,
                fillOpacity: 0,
            });
            marker.setRadius(0.01);
            setMarkerInteractivity(marker, false);
        } else {
            marker.setStyle(marker._baseStyle);
            marker.setRadius(marker._baseRadius || NODE_MIN_RADIUS);
            setMarkerInteractivity(marker, true);
        }
    });

    if (state.selectedMarker) {
        highlightMarker(state.selectedMarker);
    }
}

function applyEntityStyling() {
    if (state.nodes.length === 0) {
        return;
    }

    const { turnContext, entityStats } = getSelectedEntityStats();
    let maxMetric = 0;
    if (turnContext && entityStats) {
        if (state.metricMode === 'percent') {
            ensurePercentMetrics(entityStats, turnContext);
            maxMetric = Math.max(0, safeNumber(entityStats.maxPercent, 0));
        } else {
            maxMetric = Math.max(0, safeNumber(entityStats.topCityVotes, 0));
        }
    }

    state.currentMaxMetric = maxMetric;

    state.nodes.forEach((node, nodeIndex) => {
        const marker = state.markerByNodeId.get(node.id);
        if (!marker) {
            return;
        }

        let metric = 0;
        let hasTurnData = false;
        if (turnContext && entityStats) {
            hasTurnData = !!turnContext.hasTurnDataByNode[nodeIndex];
            if (state.metricMode === 'percent') {
                metric = Math.max(0, safeNumber(entityStats.percentByNode[nodeIndex], 0));
            } else {
                metric = Math.max(0, safeNumber(entityStats.votesByNode[nodeIndex], 0));
            }
        }

        const radius = getVoteRadius(metric, maxMetric);
        const baseStyle = {
            fillColor: getVoteColor(metric, maxMetric),
            color: '#ffffff',
            weight: hasTurnData && metric > 0 ? 0.55 : 0.35,
            opacity: 0.7,
            fillOpacity: getVoteFillOpacity(metric, maxMetric),
        };

        marker._metricValue = metric;
        marker._baseRadius = radius;
        marker._baseStyle = baseStyle;
        marker._hiddenByZoom = false;
        marker.setRadius(radius);
        marker.setStyle(baseStyle);
    });

    updateLegend(maxMetric);
    updateEntitySummary();
    applyDeclutter();

    if (state.selectedNode) {
        showNodeInfo(state.selectedNode);
    }
}

function configureTurnSelector() {
    const turns = collectTurns(state.nodes, state.selectedCargo);
    if (turns.length === 0) {
        turnSelectEl.disabled = true;
        turnSelectEl.innerHTML = '<option value="">Sem turnos</option>';
        state.selectedTurn = null;
        return;
    }

    turnSelectEl.disabled = false;
    turnSelectEl.innerHTML = '';
    turns.forEach((turn) => {
        const option = document.createElement('option');
        option.value = turn;
        option.textContent = formatTurnLabel(turn);
        turnSelectEl.appendChild(option);
    });

    if (!state.selectedTurn || !turns.includes(String(state.selectedTurn))) {
        state.selectedTurn = turns[0];
    }
    turnSelectEl.value = String(state.selectedTurn);
}

function getCurrentEntityOptions() {
    if (!state.selectedCargo || !state.selectedTurn) {
        return [];
    }
    if (state.entityType === 'candidate') {
        return collectCandidates(state.nodes, state.selectedCargo, state.selectedTurn);
    }
    return collectParties(state.nodes, state.selectedCargo, state.selectedTurn);
}

function configureEntitySelector() {
    let options = getCurrentEntityOptions();
    if (state.entityType === 'candidate' && options.length === 0) {
        state.entityType = 'party';
        entityTypeSelectEl.value = 'party';
        options = getCurrentEntityOptions();
    }

    if (options.length === 0) {
        entitySelectEl.disabled = true;
        entitySelectEl.innerHTML = '<option value="">Sem entidades</option>';
        state.entityKey = null;
        return;
    }

    entitySelectEl.disabled = false;
    entitySelectEl.innerHTML = '';
    options.forEach((item) => {
        const option = document.createElement('option');
        option.value = item.key;
        option.textContent = item.label;
        entitySelectEl.appendChild(option);
    });

    const optionKeys = options.map((item) => item.key);
    if (!state.entityKey || !optionKeys.includes(state.entityKey)) {
        state.entityKey = options[0].key;
    }
    entitySelectEl.value = state.entityKey;
}

function configureCargoSelector() {
    const cargos = collectCargos(state.nodes);
    if (cargos.length === 0) {
        filterPanelEl.hidden = true;
        state.selectedCargo = null;
        state.selectedTurn = null;
        state.entityKey = null;
        setStatus('Dados eleitorais indisponiveis para este conjunto.', true);
        return;
    }

    filterPanelEl.hidden = false;
    cargoSelectEl.disabled = false;
    cargoSelectEl.innerHTML = '';
    cargos.forEach((cargoKey) => {
        const option = document.createElement('option');
        option.value = cargoKey;
        option.textContent = formatCargoLabel(cargoKey);
        cargoSelectEl.appendChild(option);
    });

    state.selectedCargo = getDefaultCargo(cargos);
    cargoSelectEl.value = state.selectedCargo;
    configureTurnSelector();
    configureEntitySelector();
}

function rebuildCitySearch(nodes) {
    state.nodeByNormalizedName = new Map();
    state.nodeSearchEntries = [];
    cityListEl.innerHTML = '';

    nodes
        .slice()
        .sort((a, b) => a.name.localeCompare(b.name, 'pt-BR'))
        .forEach((node) => {
            const normalized = normalizeText(node.name);
            if (!state.nodeByNormalizedName.has(normalized)) {
                state.nodeByNormalizedName.set(normalized, node);
            }
            state.nodeSearchEntries.push({ normalized, node });

            const option = document.createElement('option');
            option.value = node.name;
            cityListEl.appendChild(option);
        });
}

function findNodeBySearch(text) {
    const normalized = normalizeText(text);
    if (!normalized) {
        return null;
    }

    const exact = state.nodeByNormalizedName.get(normalized);
    if (exact) {
        return exact;
    }

    let firstPrefix = null;
    let firstContains = null;
    state.nodeSearchEntries.forEach((entry) => {
        if (!firstPrefix && entry.normalized.startsWith(normalized)) {
            firstPrefix = entry.node;
        }
        if (!firstContains && entry.normalized.includes(normalized)) {
            firstContains = entry.node;
        }
    });
    return firstPrefix || firstContains;
}

function handleCitySearch() {
    const query = citySearchEl.value.trim();
    if (!query) {
        searchHintEl.textContent = 'Digite um municipio para centralizar e destacar.';
        return;
    }

    const node = findNodeBySearch(query);
    if (!node) {
        searchHintEl.textContent = `Municipio nao encontrado: "${query}".`;
        return;
    }

    searchHintEl.textContent = `Municipio selecionado: ${node.name}.`;
    focusNode(node, true);
    applyDeclutter();
}

function bindControlEvents() {
    cargoSelectEl.addEventListener('change', () => {
        state.selectedCargo = cargoSelectEl.value;
        state.selectedTurn = null;
        state.entityKey = null;
        configureTurnSelector();
        configureEntitySelector();
        applyEntityStyling();
    });

    turnSelectEl.addEventListener('change', () => {
        state.selectedTurn = turnSelectEl.value;
        state.entityKey = null;
        configureEntitySelector();
        applyEntityStyling();
    });

    metricSelectEl.addEventListener('change', () => {
        state.metricMode = metricSelectEl.value === 'percent' ? 'percent' : 'absolute';
        applyEntityStyling();
    });

    entityTypeSelectEl.addEventListener('change', () => {
        state.entityType = entityTypeSelectEl.value === 'candidate' ? 'candidate' : 'party';
        state.entityKey = null;
        configureEntitySelector();
        applyEntityStyling();
    });

    entitySelectEl.addEventListener('change', () => {
        state.entityKey = entitySelectEl.value;
        applyEntityStyling();
    });

    citySearchBtnEl.addEventListener('click', () => {
        handleCitySearch();
    });

    citySearchEl.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
            event.preventDefault();
            handleCitySearch();
        }
    });
}

function renderGraph(payload) {
    const rawNodes = Array.isArray(payload?.nodes) ? payload.nodes : [];
    const rawEdges = Array.isArray(payload?.edges) ? payload.edges : [];

    const nodes = rawNodes.map(normalizeNode).filter(Boolean);
    const edges = rawEdges.map(normalizeEdge).filter(Boolean);

    if (nodes.length === 0) {
        throw new Error('Nenhum no valido encontrado no arquivo de dados.');
    }

    state.nodes = nodes;
    state.edges = edges;
    state.selectedMarker = null;
    state.selectedNode = null;
    state.markerByNodeId = new Map();
    state.edgeLayers = [];
    state.nodeByNormalizedName = new Map();
    state.nodeSearchEntries = [];
    state.nodeIndexById = new Map();
    state.turnContexts = new Map();
    state.metricMode = metricSelectEl.value === 'percent' ? 'percent' : 'absolute';
    state.entityType = entityTypeSelectEl.value === 'candidate' ? 'candidate' : 'party';
    state.entityKey = null;

    edgeGroup.clearLayers();
    nodeGroup.clearLayers();
    cityInfoEl.hidden = true;

    const nodeMap = new Map(nodes.map((node) => [node.id, node]));
    let renderedEdges = 0;
    edges.forEach((edge) => {
        const source = nodeMap.get(edge.source);
        const target = nodeMap.get(edge.target);
        if (!source || !target) {
            return;
        }

        const line = L.polyline(
            [
                [source.lat, source.lng],
                [target.lat, target.lng],
            ],
            BASE_EDGE_STYLE
        );
        line._baseOpacity = BASE_EDGE_STYLE.opacity;
        line.on('mouseover', function () {
            if (this._baseOpacity <= 0) {
                return;
            }
            this.setStyle({ color: '#ffea00', opacity: Math.min(0.5, this._baseOpacity + 0.36), weight: 1.6 });
        });
        line.on('mouseout', function () {
            this.setStyle({
                ...BASE_EDGE_STYLE,
                opacity: this._baseOpacity,
            });
        });
        line.addTo(edgeGroup);
        state.edgeLayers.push(line);
        renderedEdges += 1;
    });

    nodes.forEach((node) => {
        const marker = L.circleMarker([node.lat, node.lng], {
            radius: NODE_MIN_RADIUS,
            fillColor: '#2f3f56',
            color: '#ffffff',
            weight: 0.35,
            opacity: 0.7,
            fillOpacity: 0.08,
        });

        marker.on('mouseover', function () {
            if (marker._hiddenByZoom && state.selectedMarker !== marker) {
                return;
            }
            if (state.selectedMarker && state.selectedMarker !== marker) {
                return;
            }
            highlightMarker(marker);
            showNodeInfo(node);
        });

        marker.on('mouseout', function () {
            if (state.selectedMarker && state.selectedMarker === marker) {
                return;
            }
            resetMarkerStyle(marker);
            clearNodeInfo();
        });

        marker.on('click', function (event) {
            L.DomEvent.stopPropagation(event);
            if (state.selectedMarker === marker) {
                clearSelection();
                applyDeclutter();
                return;
            }
            focusNode(node);
            applyDeclutter();
        });

        marker.addTo(nodeGroup);
        state.markerByNodeId.set(node.id, marker);
    });

    map.off('click');
    map.on('click', () => {
        clearSelection();
        applyDeclutter();
    });

    const bounds = L.latLngBounds(nodes.map((node) => [node.lat, node.lng]));
    if (bounds.isValid()) {
        map.fitBounds(bounds, { padding: [30, 30], maxZoom: 8 });
    }

    buildTurnContexts(nodes);
    configureCargoSelector();
    rebuildCitySearch(nodes);
    applyEntityStyling();

    totalCitiesEl.textContent = String(nodes.length);
    totalEdgesEl.textContent = String(renderedEdges);

    const contextText = state.entityKey
        ? `${formatEntityTypeLabel(state.entityType).toLowerCase()} ${getSelectedEntityLabel()} em ${formatCargoLabel(state.selectedCargo)}, ${formatTurnLabel(state.selectedTurn)}`
        : 'contexto sem entidade selecionada';
    setStatus(
        `Dados carregados (${state.loadedFile || 'arquivo local'}): ${nodes.length} cidades, ${renderedEdges} conexoes, ${contextText}.`
    );
}

async function fetchFirstAvailable(paths) {
    let lastError = null;
    for (const path of paths) {
        try {
            const response = await fetch(path, { cache: 'default' });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const payload = await response.json();
            writeCachedPayload(path, payload);
            return { payload, path, fromCache: false };
        } catch (error) {
            lastError = error;
        }
    }

    const cached = readCachedPayload();
    if (cached?.payload) {
        return {
            payload: cached.payload,
            path: `${cached.path || 'cache-local'} (cache local)`,
            fromCache: true,
        };
    }

    throw lastError || new Error('Nenhum arquivo de dados foi carregado.');
}

async function loadGraphData() {
    hideError();
    setStatus('Carregando dados do grafo...', true);

    try {
        const { payload, path, fromCache } = await fetchFirstAvailable([
            'mg_graph_data.compact.json',
            'mg_graph_data.json',
        ]);
        state.loadedFile = path;
        renderGraph(payload);
        if (fromCache) {
            setStatus(`Dados carregados de cache local (${path}).`, false);
        }
    } catch (error) {
        console.error('Failed to load map data:', error);
        showError(`Detalhe: ${error.message}`);
    }
}

retryBtnEl.addEventListener('click', () => {
    loadGraphData();
});

map.on('zoomend', () => {
    applyDeclutter();
});

bindControlEvents();
loadGraphData();
