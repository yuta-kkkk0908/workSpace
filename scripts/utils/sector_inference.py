from __future__ import annotations

import re


UNKNOWN_TOKENS = {"", "unknown", "不明", "-", "n/a", "na"}

DISPLAY_MAP = {
    "construction_infrastructure": "建設・インフラ",
    "healthcare_services": "ヘルスケア",
    "food_beverage": "食品・飲料",
    "real_estate": "不動産",
    "retail_consumer": "小売・消費",
    "electronics_trading": "電子部材・商社",
    "internet_media_game": "ネット・ゲーム",
    "internet_media_ad": "ネット・広告",
    "software_it": "ソフトウェア・IT",
    "crypto_fintech": "暗号資産・フィンテック",
    "renewable_energy": "再生可能エネルギー",
    "materials_chemicals": "素材・化学",
    "auto_parts": "自動車部品",
    "cybersecurity_it": "サイバーセキュリティ",
    "engineering_it": "エンジニアリングIT",
    "cloud_it_services": "クラウド・ITサービス",
    "biotech": "バイオ",
    "facility_services": "施設サービス",
    "parking_mobility": "駐車・モビリティ",
    "consumer_goods": "消費財",
    "rubber_industrial": "ゴム・産業材",
    "housing_equipment": "住宅設備",
    "matching_services": "マッチングサービス",
    "inspection_services": "検査サービス",
    "machinery_capital_goods": "機械・設備投資",
    "consulting_services": "コンサルティング",
    "electronics_components": "電子部品",
    "electronics_equipment": "電子機器",
    "semiconductor_equipment": "半導体装置",
    "precision_electronics": "精密電子",
    "business_process_services": "BPO・業務支援",
    "apparel_retail": "アパレル小売",
    "apparel_wholesale": "アパレル卸",
    "materials_trading": "素材・商社",
    "medical_devices": "医療機器",
    "printing_ad_services": "印刷・広告",
    "office_stationery": "文具・オフィス用品",
    "healthcare_wholesale": "医薬・ヘルスケア卸",
    "insurance_financial": "保険・金融",
    "securities_fintech": "証券・フィンテック",
    "finance": "金融",
    "shipping_logistics": "海運・物流",
    "consumer_services": "生活サービス",
    "reuse_retail": "リユース小売",
    "logistics": "物流",
    "marketing_hr_services": "マーケ・人材サービス",
    "rental_construction_equipment": "建機レンタル",
    "geology_infrastructure": "地質・インフラ",
    "event_driven": "イベント性",
    "growth_sensitive": "成長株",
    "risk_appetite_sensitive": "リスク選好",
    "rate_sensitive": "金利敏感",
    "rate_sensitive_financial": "金利敏感・金融",
    "market_volume_sensitive": "売買代金連動",
    "export_fx_cyclical": "輸出・為替循環",
    "global_trade_sensitive": "グローバル景気",
    "cyclical_input_cost_sensitive": "コスト循環",
    "domestic_consumption_sensitive": "国内消費",
    "domestic_defensive": "内需ディフェンシブ",
    "defensive_growth_sensitive": "ディフェンシブ成長",
    "domestic_defensive_order_sensitive": "内需・受注敏感",
    "domestic_order_sensitive": "内需・受注敏感",
    "domestic_service_cycle": "国内サービス循環",
    "ad_cycle_sensitive": "広告循環",
    "policy_rate_sensitive": "政策金利敏感",
    "binary_event_sensitive": "イベントバイナリ",
    "deal_terms_sensitive": "M&A・条件敏感",
}


def _norm_text(*parts: str) -> str:
    return " ".join(str(p or "") for p in parts).strip().lower()


def is_unknown_sector(v: str) -> bool:
    return str(v or "").strip().lower() in UNKNOWN_TOKENS


def display_sector(raw: str) -> str:
    s = str(raw or "").strip()
    if is_unknown_sector(s):
        return "不明"
    return DISPLAY_MAP.get(s, s)


def infer_sector_context(*parts: str) -> tuple[str, str, str]:
    text = _norm_text(*parts)
    if not text:
        return "unknown", "unknown", "unknown"
    patterns = [
        (r"(tob|mbo|買収|売却|再編)", ("event_driven", "deal_terms_sensitive", "keyword_event")),
        (r"(半導体|semiconductor|chip|chipset)", ("semiconductor_equipment", "semiconductor_cycle_sensitive", "keyword_semiconductor")),
        (r"(software|saas|cloud|dx|it|システム|システム開発)", ("software_it", "growth_sensitive", "keyword_software")),
        (r"(biotech|biological|clinical|trial|バイオ|医薬|製薬|drug)", ("biotech", "binary_event_sensitive", "keyword_biotech")),
        (r"(real estate|reit|不動産)", ("real_estate", "rate_sensitive", "keyword_realestate")),
        (r"(bank|banks|証券|insurance|保険|fintech|finance|金融)", ("insurance_financial", "rate_sensitive_financial", "keyword_financial")),
        (r"(auto|car|motor|自動車|車体|部品)", ("auto_parts", "export_fx_cyclical", "keyword_auto")),
        (r"(retail|consumer|小売|飲食|食品|外食|スーパー)", ("retail_consumer", "domestic_consumption_sensitive", "keyword_consumer")),
        (r"(chemic|materials|rubber|素材|化学|ゴム)", ("materials_chemicals", "cyclical_input_cost_sensitive", "keyword_materials")),
        (r"(machinery|equipment|機械|装置|工具)", ("machinery_capital_goods", "export_fx_cyclical", "keyword_machinery")),
        (r"(logistics|shipping|海運|物流|運輸|倉庫)", ("logistics", "global_trade_sensitive", "keyword_logistics")),
        (r"(ad|media|internet|game|ネット|広告|ゲーム|メディア)", ("internet_media_ad", "ad_cycle_sensitive", "keyword_media")),
        (r"(energy|electric|power|gas|電力|ガス|エネルギー)", ("policy_rate_sensitive", "policy_rate_sensitive", "keyword_energy")),
        (r"(construction|infra|infrastructure|建設|土木|インフラ)", ("construction_infrastructure", "domestic_defensive_order_sensitive", "keyword_construction")),
        (r"(medical|device|health|医療|ヘルスケア)", ("medical_devices", "defensive_growth_sensitive", "keyword_healthcare")),
        (r"(consult|hr|人材|採用|研修|コンサル)", ("consulting_services", "growth_sensitive", "keyword_services")),
    ]
    for pat, ctx in patterns:
        if re.search(pat, text):
            return ctx
    return "unknown", "unknown", "unknown"


def resolve_sector_label(
    sector_group: str = "",
    *,
    instrument_sector: str = "",
    company: str = "",
    signal_type: str = "",
    title: str = "",
) -> str:
    for raw in (sector_group, instrument_sector):
        if not is_unknown_sector(raw):
            return display_sector(raw)
    inferred_group, _, _ = infer_sector_context(company, signal_type, title)
    return display_sector(inferred_group)
