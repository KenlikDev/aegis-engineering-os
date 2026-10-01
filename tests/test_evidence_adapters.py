            integration_delivery_evidence(
                result,
                repository=REPOSITORY,
                observed_at="2026-09-28T18:00:00Z",
            )

    def test_integration_delivery_rejects_validation_head_mismatch(self):
        result = {
            "status": "verified",
            "work_item_id": "150",
            "traceability_verified": True,
            "pull_request": {
                "number": 150,
                "url": "https://github.com/kenlikdev/aegis-engineering-os/pull/150",
                "head": "ai/feature/150-integration-delivery-provenance",
                "head_sha": TARGET_SHA,
                "base": "ai/integration",
                "merged": True,
                "merge_commit_sha": TARGET_SHA,
            },
            "validation": {
                "id": 1500,
                "workflow": ".github/workflows/validate.yml",
                "status": "completed",
                "conclusion": "success",
                "head_sha": SOURCE_SHA,
                "url": "https://github.com/kenlikdev/aegis-engineering-os/actions/runs/1500",
            },
            "post_merge_validation": {
                "id": 1501,
                "workflow": ".github/workflows/validate.yml",
                "status": "completed",
                "conclusion": "success",
                "head_sha": TARGET_SHA,
                "validated_sha": TARGET_SHA,
                "evidence_type": "branch-push",
                "pull_request_number": null,
                "url": "https://github.com/kenlikdev/aegis-engineering-os/actions/runs/1501",
            },
            "integration": {
                "branch": "ai/integration",
                "sha": TARGET_SHA,
                "protected": True,
                "contains_merge_commit": True,
            },
            "work_item": {
                "state_after": "integration",
                "transition_verified": True,
            },
        }

        with self.assertRaisesRegex(
            EvidenceContractError,
            "validation head does not match",
        ):
            integration_delivery_evidence(
                result,
                repository=REPOSITORY,
                observed_at="2026-09-28T18:00:00Z",
            )

    def test_runtime_preflight_without_agent_server_is_verified(self):
        result = {
            "status": "verified",
            "profile_name": "development-local",
            "provider": "ollama",
            "surface": "local",
            "integration": "openhands_llm_ollama",
            "connection_mode": "local",
            "model": "gemma4:31b",
            "ollama_base_url": "http://127.0.0.1:11434",