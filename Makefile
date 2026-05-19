.PHONY: validate new-topic export-sample diff-topic investment-adaptive investment-rule-check investment-tag-index investment-backtest-expand investment-validate-seeds investment-generated-inventory investment-quality investment-seed-compare inv-daily inv-deep inv-deep-cache daily-missing
PYTHON ?= python3
TODAY := $(shell $(PYTHON) -c "from datetime import date; print(date.today().isoformat())")

validate:
	$(PYTHON) scripts/validate_topics.py

new-topic:
	@if [ -z "$(TOPIC)" ]; then \
		echo "Usage: make new-topic TOPIC=product-research PURPOSE='目的'"; \
		exit 1; \
	fi
	$(PYTHON) scripts/new_topic.py "$(TOPIC)" $(if $(PURPOSE),--purpose "$(PURPOSE)",)

export-sample:
	@if [ -z "$(TOPIC)" ]; then \
		echo "Usage: make export-sample TOPIC=topic-slug SAMPLE=sample-slug"; \
		exit 1; \
	fi
	$(PYTHON) scripts/export_sample_topic.py "$(TOPIC)" $(if $(SAMPLE),--sample-slug "$(SAMPLE)",)

diff-topic:
	@if [ -z "$(LEFT)" ] || [ -z "$(RIGHT)" ]; then \
		echo "Usage: make diff-topic LEFT=topics/foo RIGHT=sample-topics/foo-demo"; \
		exit 1; \
	fi
	$(PYTHON) scripts/diff_topic.py "$(LEFT)" "$(RIGHT)"

investment-rule-check:
	$(PYTHON) scripts/investment/analysis/rule_check_market_outcomes.py --date "$${DATE:-$$(date +%F)}" --min-count "$${MIN_COUNT:-8}"

investment-tag-index:
	$(PYTHON) scripts/investment/analysis/build_investment_tag_index.py

investment-validate-seeds:
	$(PYTHON) scripts/validate_topics.py

investment-generated-inventory:
	$(PYTHON) scripts/investment/analysis/list_investment_generated.py --date "$${DATE:-$$(date +%F)}"

investment-quality:
	$(PYTHON) scripts/investment/analysis/analyze_investment_quality.py --date "$${DATE:-$$(date +%F)}"

investment-seed-compare:
	$(PYTHON) scripts/investment/analysis/compare_investment_seed_lists.py --date "$${DATE:-$$(date +%F)}" --seed-list "$${LEFT_SEED:-rough_backtest_light}" --seed-list "$${RIGHT_SEED:-rough_backtest_full}" --min-count "$${MIN_COUNT:-8}"

investment-adaptive:
	@if [ -f "topics/investment-research/inbox/$${DATE:-$$(date +%F)}-rough-backtest-outcomes-batch-1.md" ]; then \
		$(PYTHON) scripts/investment/analysis/analyze_market_outcomes.py --date "$${DATE:-$$(date +%F)}" --seed-list "$${SEED_LIST:-rough_backtest_light}"; \
		$(PYTHON) scripts/investment/analysis/rule_check_market_outcomes.py --date "$${DATE:-$$(date +%F)}" --seed-list "$${SEED_LIST:-rough_backtest_light}" --min-count "$${MIN_COUNT:-8}"; \
		$(PYTHON) scripts/investment/analysis/analyze_long_rule_reproducibility.py --date "$${DATE:-$$(date +%F)}"; \
	else \
		echo "skip investment adaptive analysis: outcome file not found for $${DATE:-$$(date +%F)}"; \
	fi
	@if [ -f "topics/investment-research/inbox/$${DATE:-$$(date +%F)}-long-rule-reproducibility.json" ] && [ -f "topics/investment-research/inbox/$${DATE:-$$(date +%F)}-short-conviction-data.json" ]; then \
		$(PYTHON) scripts/investment/analysis/generate_rule_dashboard.py --date "$${DATE:-$$(date +%F)}"; \
		$(PYTHON) scripts/investment/analysis/update_rule_history.py --date "$${DATE:-$$(date +%F)}"; \
	else \
		echo "skip rule dashboard: long/short rule inputs not ready for $${DATE:-$$(date +%F)}"; \
	fi
	$(PYTHON) scripts/investment/analysis/build_investment_tag_index.py
	$(PYTHON) scripts/investment/analysis/analyze_investment_quality.py --date "$${DATE:-$$(date +%F)}"
	$(PYTHON) scripts/investment/analysis/list_investment_generated.py --date "$${DATE:-$$(date +%F)}"

investment-backtest-expand:
	$(PYTHON) scripts/investment/collect/collect_kabutan_surprise_signals.py --date "$${DATE:-$$(date +%F)}" $${CACHE_ONLY:+--cache-only}
	$(PYTHON) scripts/investment/collect/collect_kabutan_short_signals.py --date "$${DATE:-$$(date +%F)}" $${CACHE_ONLY:+--cache-only}
	$(PYTHON) scripts/investment/backtest/fill_market_outcomes.py --date "$${DATE:-$$(date +%F)}" --seed-list "$${SEED_LIST:-rough_backtest_full}" $${CACHE_ONLY:+--cache-only}
	$(PYTHON) scripts/investment/backtest/fill_sector_context.py --date "$${DATE:-$$(date +%F)}"
	$(PYTHON) scripts/extract_margin_context.py --date "$${DATE:-$$(date +%F)}"
	$(PYTHON) scripts/investment/backtest/fill_technical_context.py --date "$${DATE:-$$(date +%F)}" $${CACHE_ONLY:+--cache-only}
	$(PYTHON) scripts/investment/backtest/fill_borrow_context.py --date "$${DATE:-$$(date +%F)}" $${CACHE_ONLY:+--cache-only}
	$(PYTHON) scripts/investment/backtest/fill_market_context.py --date "$${DATE:-$$(date +%F)}" $${CACHE_ONLY:+--cache-only}
	$(PYTHON) scripts/investment/backtest/fill_sector_market_context.py --date "$${DATE:-$$(date +%F)}" $${CACHE_ONLY:+--cache-only}
	$(PYTHON) scripts/investment/analysis/analyze_market_outcomes.py --date "$${DATE:-$$(date +%F)}" --seed-list "$${SEED_LIST:-rough_backtest_full}"
	$(PYTHON) scripts/investment/analysis/analyze_cross_factors.py --date "$${DATE:-$$(date +%F)}" --seed-list "$${SEED_LIST:-rough_backtest_full}"
	$(PYTHON) scripts/investment/analysis/prioritize_unknowns.py --date "$${DATE:-$$(date +%F)}"
	$(PYTHON) scripts/investment/analysis/rule_check_market_outcomes.py --date "$${DATE:-$$(date +%F)}" --seed-list "$${SEED_LIST:-rough_backtest_full}" --min-count "$${MIN_COUNT:-8}"
	$(PYTHON) scripts/investment/analysis/analyze_long_rule_reproducibility.py --date "$${DATE:-$$(date +%F)}"
	$(PYTHON) scripts/investment/analysis/classify_short_use_cases.py --date "$${DATE:-$$(date +%F)}"
	$(PYTHON) scripts/investment/analysis/classify_short_readiness.py --date "$${DATE:-$$(date +%F)}"
	$(PYTHON) scripts/investment/analysis/analyze_short_high_readiness.py --date "$${DATE:-$$(date +%F)}"
	$(PYTHON) scripts/investment/analysis/generate_short_watch_report.py --date "$${DATE:-$$(date +%F)}"
	$(PYTHON) scripts/investment/analysis/analyze_short_chart_windows.py --date "$${DATE:-$$(date +%F)}"
	$(PYTHON) scripts/investment/analysis/analyze_short_chart_window_stats.py --date "$${DATE:-$$(date +%F)}"
	$(PYTHON) scripts/investment/analysis/analyze_short_rebound_risk.py --date "$${DATE:-$$(date +%F)}"
	$(PYTHON) scripts/investment/analysis/classify_short_conviction.py --date "$${DATE:-$$(date +%F)}"
	$(PYTHON) scripts/investment/analysis/generate_rule_dashboard.py --date "$${DATE:-$$(date +%F)}"
	$(PYTHON) scripts/investment/analysis/update_rule_history.py --date "$${DATE:-$$(date +%F)}"
	$(PYTHON) scripts/investment/analysis/build_investment_tag_index.py
	$(PYTHON) scripts/investment/analysis/analyze_investment_quality.py --date "$${DATE:-$$(date +%F)}"
	$(PYTHON) scripts/investment/analysis/list_investment_generated.py --date "$${DATE:-$$(date +%F)}"

inv-daily:
	$(PYTHON) scripts/run_pipeline.py daily --date "$(if $(DATE),$(DATE),$(TODAY))" --seed-list "$(if $(SEED_LIST),$(SEED_LIST),rough_backtest_light)" --min-count "$(if $(MIN_COUNT),$(MIN_COUNT),8)"

inv-deep:
	$(PYTHON) scripts/run_pipeline.py deep --date "$(if $(DATE),$(DATE),$(TODAY))" --seed-list "$(if $(SEED_LIST),$(SEED_LIST),rough_backtest_full)" --min-count "$(if $(MIN_COUNT),$(MIN_COUNT),8)"

inv-deep-cache:
	$(PYTHON) scripts/run_pipeline.py deep --date "$(if $(DATE),$(DATE),$(TODAY))" --seed-list "$(if $(SEED_LIST),$(SEED_LIST),rough_backtest_full)" --min-count "$(if $(MIN_COUNT),$(MIN_COUNT),8)" --cache-only

daily-missing:
	$(PYTHON) scripts/check_daily_missing.py --date "$(if $(DATE),$(DATE),today)" --days "$(if $(DAYS),$(DAYS),7)"

investment-signal-missing:
	$(PYTHON) scripts/investment/signals/check_investment_signal_missing.py --date "$(if $(DATE),$(DATE),$(TODAY))"

investment-entry-candidates:
	$(PYTHON) scripts/investment/signals/generate_entry_candidates.py --date "$(if $(DATE),$(DATE),$(TODAY))"

investment-db-init:
	$(PYTHON) scripts/data/init_investment_db.py

investment-db-ingest:
	$(PYTHON) scripts/data/ingest_investment_db.py $(if $(DATE),--date "$(DATE)",)

investment-auto-night:
	$(PYTHON) scripts/run_investment_automation.py --mode night --date "$(if $(DATE),$(DATE),$(TODAY))" --python "$(PYTHON)"

investment-auto-morning:
	$(PYTHON) scripts/run_investment_automation.py --mode morning --date "$(if $(DATE),$(DATE),$(TODAY))" --python "$(PYTHON)"

investment-db-brief:
	$(PYTHON) scripts/data/build_today_brief_from_db.py --date "$(if $(DATE),$(DATE),$(TODAY))"

topics-db-init:
	$(PYTHON) scripts/data/init_topics_db.py

topics-db-ingest:
	$(PYTHON) scripts/data/ingest_topics_db.py $(if $(DATE),--date "$(DATE)",)

topics-db-brief:
	$(PYTHON) scripts/data/build_today_topics_brief_from_db.py --date "$(if $(DATE),$(DATE),$(TODAY))"

needs-db-init:
	$(PYTHON) scripts/data/init_needs_db.py

needs-db-ingest:
	$(PYTHON) scripts/data/ingest_needs_db.py $(if $(DATE),--date "$(DATE)",)

needs-ai-queue:
	$(PYTHON) scripts/build_needs_ai_queue.py --limit "$(if $(LIMIT),$(LIMIT),20)"

needs-ai-apply:
	$(PYTHON) scripts/apply_needs_triage.py --input "$(INPUT)"

ops-night:
	$(PYTHON) scripts/run_ops_scheduler.py --slot night --date "$(if $(DATE),$(DATE),$(TODAY))" --python "$(PYTHON)"

ops-inv-morning:
	$(PYTHON) scripts/run_ops_scheduler.py --slot inv-morning --date "$(if $(DATE),$(DATE),$(TODAY))" --python "$(PYTHON)"

ops-inv-noon:
	$(PYTHON) scripts/run_ops_scheduler.py --slot inv-noon --date "$(if $(DATE),$(DATE),$(TODAY))" --python "$(PYTHON)"

ops-inv-evening:
	$(PYTHON) scripts/run_ops_scheduler.py --slot inv-evening --date "$(if $(DATE),$(DATE),$(TODAY))" --python "$(PYTHON)"

ops-inv-scenario:
	$(PYTHON) scripts/run_ops_scheduler.py --slot inv-scenario --date "$(if $(DATE),$(DATE),$(TODAY))" --python "$(PYTHON)"

inv-scenario-message:
	$(PYTHON) scripts/notify/render_opening_scenarios_discord_message.py --date "$(if $(DATE),$(DATE),$(TODAY))" --fallback-days 3

build-execution-plan:
	$(PYTHON) scripts/investment/signals/build_execution_plan.py --date "$(if $(DATE),$(DATE),$(TODAY))" --fallback-days "$(if $(FALLBACK_DAYS),$(FALLBACK_DAYS),3)"

inv-signal-message:
	$(PYTHON) scripts/notify/render_market_signals_discord_message.py --date "$(if $(DATE),$(DATE),$(TODAY))" --fallback-days 3

inv-paper-stats-message:
	$(PYTHON) scripts/notify/render_paper_stats_discord_message.py --date "$(if $(DATE),$(DATE),$(TODAY))" --fallback-days "$(if $(FALLBACK_DAYS),$(FALLBACK_DAYS),3)"

generic-daily-message:
	$(PYTHON) scripts/notify/render_generic_topics_discord_message.py --date "$(if $(DATE),$(DATE),$(TODAY))"

scenario-bot-post:
	$(PYTHON) scripts/notify/post_scenarios_bot.py --date "$(if $(DATE),$(DATE),$(TODAY))" --fallback-days "$(if $(FALLBACK_DAYS),$(FALLBACK_DAYS),3)" --max-posts "$(if $(MAX_POSTS),$(MAX_POSTS),12)" --watch-posts "$(if $(WATCH_POSTS),$(WATCH_POSTS),4)" --min-trade-posts "$(if $(MIN_TRADE_POSTS),$(MIN_TRADE_POSTS),3)" --dedupe-hours "$(if $(DEDUPE_HOURS),$(DEDUPE_HOURS),6)"

scenario-bot-sync:
	$(PYTHON) scripts/notify/sync_scenario_replies_bot.py --limit "$(if $(LIMIT),$(LIMIT),100)"

paper-exit-timing:
	$(PYTHON) scripts/investment/backtest/analyze_exit_timing.py --out-date "$(if $(DATE),$(DATE),$(TODAY))" --mode "$(if $(MODE),$(MODE),all)" $(if $(START),--start-date "$(START)",) $(if $(END),--end-date "$(END)",)

watch-promotion:
	$(PYTHON) scripts/investment/backtest/analyze_watch_promotion.py --out-date "$(if $(DATE),$(DATE),$(TODAY))" $(if $(START),--start-date "$(START)",) $(if $(END),--end-date "$(END)",) $(if $(MIN_SAMPLES),--min-samples "$(MIN_SAMPLES)",) $(if $(MIN_WR),--min-winrate "$(MIN_WR)",) $(if $(MIN_RET),--min-avg-ret "$(MIN_RET)",) $(if $(LADDER),--ladder,)

paper-stats:
	$(PYTHON) scripts/investment/backtest/analyze_paper_trade_stats.py --out-date "$(if $(DATE),$(DATE),$(TODAY))" --mode "$(if $(MODE),$(MODE),all)" $(if $(START),--start-date "$(START)",) $(if $(END),--end-date "$(END)",)

trade-watch-review:
	$(PYTHON) scripts/investment/backtest/generate_trade_watch_weekly_review.py --out-date "$(if $(DATE),$(DATE),$(TODAY))" $(if $(START),--start-date "$(START)",) $(if $(END),--end-date "$(END)",)
