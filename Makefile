.PHONY: validate new-topic export-sample diff-topic

validate:
	python3 scripts/validate_topics.py

new-topic:
	@if [ -z "$(TOPIC)" ]; then \
		echo "Usage: make new-topic TOPIC=product-research PURPOSE='目的'"; \
		exit 1; \
	fi
	python3 scripts/new_topic.py "$(TOPIC)" $(if $(PURPOSE),--purpose "$(PURPOSE)",)

export-sample:
	@if [ -z "$(TOPIC)" ]; then \
		echo "Usage: make export-sample TOPIC=topic-slug SAMPLE=sample-slug"; \
		exit 1; \
	fi
	python3 scripts/export_sample_topic.py "$(TOPIC)" $(if $(SAMPLE),--sample-slug "$(SAMPLE)",)

diff-topic:
	@if [ -z "$(LEFT)" ] || [ -z "$(RIGHT)" ]; then \
		echo "Usage: make diff-topic LEFT=topics/foo RIGHT=sample-topics/foo-demo"; \
		exit 1; \
	fi
	python3 scripts/diff_topic.py "$(LEFT)" "$(RIGHT)"
