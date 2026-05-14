# {{date}} External Triggers

## Topic
- slug: investment-research
- date: {{date}}
- mode: {{mode}}

## Market Snapshot
- collectedAt: {{collected_at}}
- usMarket:
  - dow: {{dow}}
  - nasdaq: {{nasdaq}}
  - sp500: {{sp500}}
  - sox: {{sox}}
- futures:
  - nikkeiFutures: {{nikkei_futures}}
  - cmeNikkei: {{cme_nikkei}}
- fxRates:
  - usdJpy: {{usd_jpy}}
- rates:
  - us10y: {{us_10y}}
  - jp10y: {{jp_10y}}
- commodities:
  - wti: {{wti}}
  - gold: {{gold}}
  - copper: {{copper}}

## External Triggers
### {{trigger_id}}: {{title}}
- triggerType: {{trigger_type}}
- source: {{source_label}}
- url: {{source_url}}
- sourceType: {{source_type}}
- verificationStatus: {{verification_status}}
- publishedAt: {{published_at}}
- eventSummary: {{event_summary}}
- keyActor: {{key_actor}}
- marketReaction:
  - usMarket: {{us_market_reaction}}
  - futures: {{futures_reaction}}
  - fx: {{fx_reaction}}
  - rates: {{rates_reaction}}
  - commodities: {{commodities_reaction}}
- affectedSectors:
  - sector: {{sector}}
    impact: {{tailwind_headwind_mixed_neutral_unknown}}
    reason: {{sector_reason}}
- japanMarketHypothesis: {{japan_market_hypothesis}}
- watchUse:
  - {{watch_use}}
- rankImpact:
  - longBias: {{upgrade_downgrade_keep_hold}}
  - shortBias: {{upgrade_downgrade_keep_hold}}
  - reason: {{rank_impact_reason}}
- checkLater:
  - T+0:
  - T+1:
  - T+5:
- outcome:
  - T+0:
  - T+1:
  - T+5:
- lesson:

## Notes
- {{notes}}
