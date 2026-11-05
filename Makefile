.PHONY: install lint test eval demo run docker lambda validate

install:
	pip install -r requirements-dev.txt

lint:
	ruff check .

test:
	pytest --cov --cov-report=term-missing

eval:
	python scripts/evaluate.py

demo:
	python scripts/build_demo.py

run:
	python -m costlens seed --if-empty && uvicorn api.main:app --reload

docker:
	docker build -t costlens . && docker run --rm -p 8000:8000 costlens

lambda:
	bash scripts/package_lambda.sh

validate:
	cfn-lint infra/template.yaml
