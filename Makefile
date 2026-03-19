SPEC_NAME := arvms_spec.pdf
INPUT_TO_SPEC_PARENT := arvms_specs/arvms_spec/
ARTIFACTS := pipeline_root/artifacts/$(INPUT_TO_SPEC_PARENT)
SRC       := pipeline_root/src

s0:
	python3 $(SRC)/S0_extractor.py pipeline_root/input/$(INPUT_TO_SPEC_PARENT)/$(SPEC_NAME)

s1:
	python3 $(SRC)/S1_normalizer.py $(ARTIFACTS)/00_raw_extract.json

s2:
	python3 $(SRC)/S2_preflight.py $(ARTIFACTS)/01_normalized.json

s3:
	python3 $(SRC)/S3_llm_structurer.py $(ARTIFACTS)/01_normalized.json

s4:
	python3 $(SRC)/S4_llm_analyzer.py $(ARTIFACTS)/03_llm_structured.json

pipeline: s0 s1 s2 s3 s4

.PHONY: s0 s1 s2 s3 s4 pipeline
