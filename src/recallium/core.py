"""Public service API for Recallium Core."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from platformdirs import user_state_dir
import threading
from typing import Any
from uuid import uuid4

from recallium.embeddings import (
    BuiltinFastEmbedProvider,
    ContentChunk,
    EmbeddingProvider,
    chunk_text_for_profile,
)
from recallium.errors import (
    EmbeddingDimensionMismatchError,
    EmbeddingGenerationError,
    NotFoundError,
    ReembeddingFailedError,
    ReembeddingInProgressError,
    ValidationError,
)
from recallium.logging import setup_logging
from recallium.model_state import read_model_state, write_model_state
from recallium.models import (
    SPACE_USER,
    SPACE_WORKSPACE,
    Memory,
    SearchResult,
    normalize_workspace_uid,
    validate_limit,
    validate_memory_create_input,
    validate_memory_update_input,
)
from recallium.config import RecalliumConfig
from recallium.search import rank_memory_candidates
from recallium.storage import SQLiteMemoryStore, utc_now_iso

_log = logging.getLogger(__name__)


def _validate_optional_string(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    if not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


class RecalliumCore:
    """High-level service object used by clients and adapters."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        immediate_reembedding_threshold: int = 20,
        config_path: Path | str | None = None,
        log_level: str | None = None,
    ) -> None:
        self.config = RecalliumConfig(config_path, log_level=log_level)
        setup_logging(self.config)

        if db_path is not None:
            selected_path = db_path
        else:
            selected_path = self.config.resolved_database_path

        _log.info(
            "RecalliumCore initialised",
            extra={"event": "core.init", "context": {"db_path": str(selected_path)}},
        )

        self.store = SQLiteMemoryStore(selected_path)
        self.embedding_provider = embedding_provider or BuiltinFastEmbedProvider()
        self.immediate_reembedding_threshold = immediate_reembedding_threshold
        self._embedding_job_lock = threading.Lock()
        self._active_deferred_embedding_jobs: dict[
            tuple[str, str | None, str | None, bool], str
        ] = {}
        self._embedding_job_threads: dict[str, threading.Thread] = {}
        startup_job = self._start_startup_reembedding()
        self._startup_reembedding_job_id = startup_job[0] if startup_job else None

    def add_memory(
        self,
        space: str,
        type: str,
        content: str,
        workspace_uid: str | None = None,
        metadata: dict[str, object] | None = None,
        source: str | None = None,
        confidence: float | None = None,
        sensitivity: str | None = None,
    ) -> Memory:
        normalized_uid = self._normalize_uid(workspace_uid)
        payload = validate_memory_create_input(
            space=space,
            memory_type=type,
            content=content,
            workspace_uid=normalized_uid,
            metadata=metadata,
            confidence=confidence,
        )

        timestamp = utc_now_iso()
        memory = Memory(
            id=str(uuid4()),
            space=payload["space"],
            type=payload["type"],
            content=payload["content"],
            workspace_uid=payload["workspace_uid"],
            metadata=payload["metadata"],
            source=_validate_optional_string("source", source),
            confidence=payload["confidence"],
            sensitivity=_validate_optional_string("sensitivity", sensitivity),
            created_at=timestamp,
            updated_at=timestamp,
        )
        chunk_embeddings = self._chunk_embed_pairs(memory.content)
        first_embedding = chunk_embeddings[0][1]
        inserted = self.store.insert_memory(
            memory, first_embedding, self.embedding_provider.embedding_profile
        )
        self.store.replace_memory_chunks(
            memory_id=inserted.id,
            embedding_profile=self.embedding_provider.embedding_profile,
            chunk_embeddings=chunk_embeddings,
        )
        _log.info(
            "memory added",
            extra={
                "event": "memory.added",
                "context": {"memory_id": inserted.id, "space": inserted.space},
            },
        )
        return inserted

    def search_user_memories(
        self,
        query: str,
        limit: int = 10,
        include_archived: bool = False,
    ) -> list[SearchResult]:
        self._ensure_scope_embeddings_ready(
            space=SPACE_USER,
            include_archived=include_archived,
            status_path="/v1/embedding/jobs",
        )
        candidates = self.store.list_chunk_candidates(
            space=SPACE_USER,
            embedding_profile=self.embedding_provider.embedding_profile,
            include_archived=include_archived,
        )
        validated_limit = validate_limit(limit)
        assert validated_limit is not None
        result = rank_memory_candidates(
            query=query,
            candidates=candidates,
            embedding_provider=self.embedding_provider,
            limit=validated_limit,
        )
        _log.info(
            "user search",
            extra={
                "event": "search.user",
                "context": {"query": query[:200], "results": len(result)},
            },
        )
        return result

    def search_workspace_memories(
        self,
        query: str,
        workspace_uid: str | None,
        limit: int = 10,
        include_archived: bool = False,
    ) -> list[SearchResult]:
        workspace_uid = _validate_optional_string("workspace_uid", workspace_uid)
        if workspace_uid is None:
            raise ValidationError("workspace_uid is required for workspace search")
        workspace_uid = self._normalize_uid(workspace_uid)
        assert workspace_uid is not None

        self._ensure_scope_embeddings_ready(
            space=SPACE_WORKSPACE,
            workspace_uid=workspace_uid,
            include_archived=include_archived,
            status_path="/v1/embedding/jobs",
        )
        candidates = self.store.list_chunk_candidates(
            space=SPACE_WORKSPACE,
            workspace_uid=workspace_uid,
            embedding_profile=self.embedding_provider.embedding_profile,
            include_archived=include_archived,
        )
        validated_limit = validate_limit(limit)
        assert validated_limit is not None
        result = rank_memory_candidates(
            query=query,
            candidates=candidates,
            embedding_provider=self.embedding_provider,
            limit=validated_limit,
        )
        _log.info(
            "workspace search",
            extra={
                "event": "search.workspace",
                "context": {
                    "query": query[:200],
                    "results": len(result),
                    "workspace_uid": workspace_uid,
                },
            },
        )
        return result

    def list_memories(
        self,
        space: str | None = None,
        type: str | None = None,
        status: str | None = None,
        workspace_uid: str | None = None,
        include_archived: bool = False,
        limit: int | None = None,
    ) -> list[Memory]:
        workspace_uid = _validate_optional_string("workspace_uid", workspace_uid)
        workspace_uid = self._normalize_uid(workspace_uid)

        return self.store.list_memories(
            space=space,
            memory_type=type,
            status=status,
            workspace_uid=workspace_uid,
            include_archived=include_archived,
            limit=validate_limit(limit),
        )

    def get_memory(self, memory_id: str) -> Memory:
        memory = self.store.get_memory(memory_id)
        touched = self.store.touch_last_accessed_at(memory_id)
        if touched is not None:
            memory = touched
        return memory

    def update_memory(
        self,
        memory_id: str,
        content: str | None = None,
        type: str | None = None,
        metadata: dict[str, object] | None = None,
        source: str | None = None,
        confidence: float | None = None,
        sensitivity: str | None = None,
    ) -> Memory:
        has_model_updates = any(
            value is not None for value in (type, content, metadata, confidence)
        )
        validated: dict[str, object]
        if has_model_updates:
            validated = validate_memory_update_input(
                memory_type=type,
                content=content,
                metadata=metadata,
                confidence=confidence,
            )
        else:
            validated = {}

        if source is not None:
            validated["source"] = _validate_optional_string("source", source)
        if sensitivity is not None:
            validated["sensitivity"] = _validate_optional_string(
                "sensitivity", sensitivity
            )
        if not validated:
            raise ValidationError("at least one update field is required")
        content_update = validated.get("content")
        if isinstance(content_update, str):
            chunk_embeddings = self._chunk_embed_pairs(content_update)
            validated["embedding"] = chunk_embeddings[0][1]
            validated["embedding_profile"] = self.embedding_provider.embedding_profile
            updated_memory = self.store.update_memory(memory_id, **validated)
            self.store.replace_memory_chunks(
                memory_id=memory_id,
                embedding_profile=self.embedding_provider.embedding_profile,
                chunk_embeddings=chunk_embeddings,
            )
            _log.info(
                "memory updated",
                extra={
                    "event": "memory.updated",
                    "context": {
                        "memory_id": updated_memory.id,
                        "space": updated_memory.space,
                    },
                },
            )
            return updated_memory

        result = self.store.update_memory(memory_id, **validated)
        _log.info(
            "memory updated",
            extra={
                "event": "memory.updated",
                "context": {"memory_id": result.id, "space": result.space},
            },
        )
        return result

    def archive_memory(self, memory_id: str) -> Memory:
        result = self.store.archive_memory(memory_id)
        _log.info(
            "memory archived",
            extra={
                "event": "memory.archived",
                "context": {"memory_id": result.id, "space": result.space},
            },
        )
        return result

    def get_embedding_job(self, job_id: str) -> dict[str, Any]:
        return self.store.get_embedding_job(job_id)

    def list_embedding_jobs(
        self, *, state: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        return self.store.list_embedding_jobs(state=state, limit=validate_limit(limit))

    def active_embedding_status(self) -> dict[str, Any]:
        startup_status_path = None
        if self._startup_reembedding_job_id is not None:
            startup_status_path = (
                f"/v1/embedding/jobs/{self._startup_reembedding_job_id}"
            )
        profile = self.embedding_provider.embedding_profile
        runtime_threads = getattr(self.embedding_provider, "runtime_threads", None)

        return {
            "embedding_profile": profile,
            "provider_status": "configured",
            "model_status": "managed_by_fastembed_cache",
            "runtime": {
                "name": "fastembed",
                "threads": runtime_threads,
                "parallel": None,
            },
            "startup_reembedding_job_id": self._startup_reembedding_job_id,
            "startup_reembedding_status_path": startup_status_path,
            "embedding_jobs_status_path": "/v1/embedding/jobs",
            "recent_embedding_jobs": self.list_embedding_jobs(limit=5),
        }

    def database_status(self) -> dict[str, object]:
        return self.store.migration_status()

    # -- workspace operations ------------------------------------------------

    def _uid_normalization(self) -> str:
        """Return the active uid_normalization setting."""
        workspace = self.config.effective_config.get("workspace")
        if isinstance(workspace, dict):
            value = workspace.get("uid_normalization", "normalize")
            if isinstance(value, str):
                return value
        return "normalize"

    def _normalize_uid(self, uid: str | None) -> str | None:
        """Normalize a workspace UID according to the active config setting."""
        if uid is None:
            return None
        if not uid.strip():
            raise ValidationError(f"workspace UID must be a non-empty string: {uid!r}")
        if self._uid_normalization() == "exact":
            return uid.strip()
        normalized = normalize_workspace_uid(uid)
        if not normalized:
            raise ValidationError(
                f"workspace UID normalizes to an empty string: {uid!r}"
            )
        return normalized

    def list_workspaces(self, *, include_archived: bool = False) -> list[str]:
        """Return distinct workspace UIDs present in the database."""
        return self.store.list_workspace_uids(include_archived=include_archived)

    def rename_workspace(self, old_uid: str, new_uid: str) -> dict[str, Any]:
        """Rename all workspace memories from old_uid to new_uid.

        Both UIDs are normalized per config before the operation.
        Returns a dict with old_uid, new_uid, and memories_updated count.
        Raises ValidationError if either UID normalizes to empty.
        Raises NotFoundError if old_uid has no matching workspace memories.
        """
        norm_old = self._normalize_uid(old_uid)
        norm_new = self._normalize_uid(new_uid)
        assert (
            norm_old is not None and norm_new is not None
        )  # _normalize_uid raises on empty

        if norm_old == norm_new:
            return {
                "old_uid": norm_old,
                "new_uid": norm_new,
                "memories_updated": 0,
            }

        count = self.store.rename_workspace(norm_old, norm_new)
        _log.info(
            "workspace renamed",
            extra={
                "event": "workspace.renamed",
                "context": {
                    "old_uid": norm_old,
                    "new_uid": norm_new,
                    "memories_updated": count,
                },
            },
        )
        return {
            "old_uid": norm_old,
            "new_uid": norm_new,
            "memories_updated": count,
        }

    def ensure_embedding_ready(self, *, timeout_seconds: float = 60.0) -> None:
        provider_ready = getattr(self.embedding_provider, "ensure_ready", None)
        if callable(provider_ready):
            provider_ready(timeout_seconds=timeout_seconds)
            return

        vector = self.embedding_provider.embed("healthcheck")
        dimensions = self.embedding_provider.embedding_profile.get("dimensions")
        if not isinstance(dimensions, int) or isinstance(dimensions, bool):
            raise EmbeddingGenerationError(
                "embedding profile must define an integer dimensions value"
            )
        if len(vector) != dimensions:
            raise EmbeddingDimensionMismatchError(
                f"unexpected embedding dimension: expected {dimensions}, got {len(vector)}"
            )

    # -- model-readiness gate --------------------------------------------------
    #
    # _ensure_model_ready() is the single entry point every embedding-dependent
    # code path must use. It compares the configured embedding model against a
    # state file, prepares (downloads/warms) the model when there is a mismatch
    # or no prior preparation, and triggers re-embedding when the model changed.
    # Future commands that need embeddings MUST call this method first.

    def _ensure_model_ready(self, *, state_dir: Path | None = None) -> None:
        """Make sure the configured embedding model is downloaded and ready.

        Compares the configured ``embedding.model`` against the last-prepared
        model recorded in the state file.  If they differ (or no state file
        exists) the provider's ``ensure_ready()`` is called and a fresh state
        file is written.  When the model *changed*, stale memories are
        re-embedded via ``_start_startup_reembedding()``.
        """
        resolved_state_dir = state_dir or Path(user_state_dir("recallium"))
        model_name = str(self.config.effective_config["embedding"]["model"])
        profile = self.embedding_provider.embedding_profile
        dimensions = profile.get("dimensions")
        profile_name = str(profile.get("profile", ""))

        existing = read_model_state(resolved_state_dir)
        if (
            existing is not None
            and existing.get("prepared_model") == model_name
            and existing.get("dimensions") == dimensions
        ):
            return  # already prepared, nothing to do

        was_previously_prepared = existing is not None
        provider_ready = getattr(self.embedding_provider, "ensure_ready", None)
        if callable(provider_ready):
            provider_ready()
        else:
            self.embedding_provider.embed("healthcheck")

        write_model_state(
            resolved_state_dir,
            model=model_name,
            dimensions=int(dimensions)
            if isinstance(dimensions, int) and not isinstance(dimensions, bool)
            else 0,
            profile=profile_name,
        )

        if was_previously_prepared:
            # Model changed — re-embed stale memories so they match the new model
            self._start_startup_reembedding()

    def _chunk_embed_pairs(self, text: str) -> list[tuple[ContentChunk, list[float]]]:
        chunks = chunk_text_for_profile(text, self.embedding_provider.embedding_profile)
        return [(chunk, self.embedding_provider.embed(chunk.text)) for chunk in chunks]

    def _ensure_scope_embeddings_ready(
        self,
        *,
        space: str,
        workspace_uid: str | None = None,
        include_archived: bool = False,
        status_path: str,
    ) -> None:
        stale_count = self.store.count_memories_needing_profile_reembedding(
            embedding_profile=self.embedding_provider.embedding_profile,
            space=space,
            workspace_uid=workspace_uid,
            include_archived=include_archived,
        )
        if stale_count == 0:
            return

        if stale_count <= self.immediate_reembedding_threshold:
            job_result = self._reembed_stale_memories(
                reason="search",
                space=space,
                workspace_uid=workspace_uid,
                include_archived=include_archived,
                fail_on_error=True,
            )
            if job_result is not None and job_result[1]:
                job_id = job_result[0]
                raise ReembeddingFailedError(
                    "runtime re-embedding failed; search results are blocked until refresh succeeds",
                    job_id=job_id,
                    status_path=f"{status_path}/{job_id}",
                )
            return

        job_id = self._start_deferred_reembedding(
            reason="search-threshold",
            stale_count=stale_count,
            space=space,
            workspace_uid=workspace_uid,
            include_archived=include_archived,
        )
        raise ReembeddingInProgressError(
            "re-embedding is in progress for the active profile",
            job_id=job_id,
            status_path=f"{status_path}/{job_id}",
        )

    def _start_startup_reembedding(self) -> tuple[str, bool] | None:
        stale_count = self.store.count_memories_needing_profile_reembedding(
            embedding_profile=self.embedding_provider.embedding_profile,
        )
        if stale_count == 0:
            return None
        if stale_count <= self.immediate_reembedding_threshold:
            return self._reembed_stale_memories(reason="startup")

        job_id = self._start_deferred_reembedding(
            reason="startup",
            stale_count=stale_count,
        )
        return (job_id, False)

    def _reembedding_scope_key(
        self,
        *,
        space: str | None,
        workspace_uid: str | None,
        include_archived: bool,
    ) -> tuple[str, str | None, str | None, bool]:
        profile_json = json.dumps(
            self.embedding_provider.embedding_profile,
            sort_keys=True,
        )
        return (profile_json, space, workspace_uid, include_archived)

    def _start_deferred_reembedding(
        self,
        *,
        reason: str,
        stale_count: int,
        space: str | None = None,
        workspace_uid: str | None = None,
        include_archived: bool = False,
    ) -> str:
        key = self._reembedding_scope_key(
            space=space,
            workspace_uid=workspace_uid,
            include_archived=include_archived,
        )

        with self._embedding_job_lock:
            existing_job_id = self._active_deferred_embedding_jobs.get(key)
            if existing_job_id is not None:
                try:
                    existing_job = self.store.get_embedding_job(existing_job_id)
                except NotFoundError:
                    self._active_deferred_embedding_jobs.pop(key, None)
                    self._embedding_job_threads.pop(existing_job_id, None)
                else:
                    if existing_job["state"] in {"pending", "in_progress"}:
                        return existing_job_id
                    self._active_deferred_embedding_jobs.pop(key, None)
                    self._embedding_job_threads.pop(existing_job_id, None)

            job_id = str(uuid4())
            self.store.create_embedding_job(
                job_id=job_id,
                state="pending",
                total_count=stale_count,
                processed_count=0,
                succeeded_count=0,
                failed_count=0,
                provider=str(self.embedding_provider.embedding_profile["provider"]),
                model=str(self.embedding_provider.embedding_profile["model"]),
                embedding_profile=self.embedding_provider.embedding_profile,
                error_message=(
                    f"deferred by {reason}: {stale_count} memories exceed immediate threshold"
                ),
                started_at=None,
                completed_at=None,
            )

            thread = threading.Thread(
                target=self._run_deferred_reembedding_job,
                kwargs={
                    "job_id": job_id,
                    "key": key,
                    "reason": reason,
                    "space": space,
                    "workspace_uid": workspace_uid,
                    "include_archived": include_archived,
                },
                name=f"recallium-reembedding-{job_id}",
                daemon=True,
            )
            self._active_deferred_embedding_jobs[key] = job_id
            self._embedding_job_threads[job_id] = thread
            thread.start()
            _log.info(
                f"deferred embedding job started: {job_id}",
                extra={
                    "event": "embedding.job_started",
                    "context": {
                        "job_id": job_id,
                        "reason": reason,
                        "stale_count": stale_count,
                    },
                },
            )

        return job_id

    def _run_deferred_reembedding_job(
        self,
        *,
        job_id: str,
        key: tuple[str, str | None, str | None, bool],
        reason: str,
        space: str | None,
        workspace_uid: str | None,
        include_archived: bool,
    ) -> None:
        try:
            self._process_reembedding_job(
                job_id=job_id,
                reason=reason,
                space=space,
                workspace_uid=workspace_uid,
                include_archived=include_archived,
            )
        finally:
            with self._embedding_job_lock:
                if self._active_deferred_embedding_jobs.get(key) == job_id:
                    self._active_deferred_embedding_jobs.pop(key, None)
                self._embedding_job_threads.pop(job_id, None)

    def _join_embedding_job(self, job_id: str, *, timeout_seconds: float = 5.0) -> None:
        with self._embedding_job_lock:
            thread = self._embedding_job_threads.get(job_id)
        if thread is not None:
            thread.join(timeout_seconds)

    def _reembed_stale_memories(
        self,
        *,
        reason: str,
        space: str | None = None,
        workspace_uid: str | None = None,
        include_archived: bool = False,
        fail_on_error: bool = False,
    ) -> tuple[str, bool] | None:
        stale_memories = self.store.list_memories_needing_profile_reembedding(
            embedding_profile=self.embedding_provider.embedding_profile,
            space=space,
            workspace_uid=workspace_uid,
            include_archived=include_archived,
        )
        if not stale_memories:
            return None

        now = utc_now_iso()
        job_id = str(uuid4())
        self.store.create_embedding_job(
            job_id=job_id,
            state="in_progress",
            total_count=len(stale_memories),
            processed_count=0,
            succeeded_count=0,
            failed_count=0,
            provider=str(self.embedding_provider.embedding_profile["provider"]),
            model=str(self.embedding_provider.embedding_profile["model"]),
            embedding_profile=self.embedding_provider.embedding_profile,
            error_message=f"triggered by {reason}",
            started_at=now,
            completed_at=None,
        )
        _log.info(
            f"embedding job started: {job_id}",
            extra={
                "event": "embedding.job_started",
                "context": {"job_id": job_id, "reason": reason},
            },
        )

        failed = self._process_reembedding_job(
            job_id=job_id,
            reason=reason,
            space=space,
            workspace_uid=workspace_uid,
            include_archived=include_archived,
            fail_on_error=fail_on_error,
            stale_memories=stale_memories,
        )
        return (job_id, failed)

    def _process_reembedding_job(
        self,
        *,
        job_id: str,
        reason: str,
        space: str | None = None,
        workspace_uid: str | None = None,
        include_archived: bool = False,
        fail_on_error: bool = False,
        stale_memories: list[Memory] | None = None,
    ) -> bool:
        if stale_memories is None:
            stale_memories = self.store.list_memories_needing_profile_reembedding(
                embedding_profile=self.embedding_provider.embedding_profile,
                space=space,
                workspace_uid=workspace_uid,
                include_archived=include_archived,
            )

        self.store.update_embedding_job(
            job_id,
            state="in_progress",
            total_count=len(stale_memories),
            processed_count=0,
            succeeded_count=0,
            failed_count=0,
            error_message=f"triggered by {reason}",
            started_at=utc_now_iso(),
            completed_at=None,
        )

        processed = 0
        succeeded = 0
        failed = 0
        failure_message: str | None = None

        for memory in stale_memories:
            processed += 1
            try:
                chunk_embeddings = self._chunk_embed_pairs(memory.content)
                self.store.refresh_memory_embedding_derived_fields(
                    memory.id,
                    embedding=chunk_embeddings[0][1],
                    embedding_profile=self.embedding_provider.embedding_profile,
                )
                self.store.replace_memory_chunks(
                    memory_id=memory.id,
                    embedding_profile=self.embedding_provider.embedding_profile,
                    chunk_embeddings=chunk_embeddings,
                )
                succeeded += 1
            except Exception as exc:
                failed += 1
                failure_message = str(exc)

            self.store.update_embedding_job(
                job_id,
                processed_count=processed,
                succeeded_count=succeeded,
                failed_count=failed,
            )

            if fail_on_error and failed > 0:
                break

        completed_at = utc_now_iso()
        final_state = "completed" if failed == 0 else "failed"
        self.store.update_embedding_job(
            job_id,
            state=final_state,
            error_message=failure_message,
            completed_at=completed_at,
        )
        if failed == 0:
            _log.info(
                f"embedding job completed: {job_id}",
                extra={
                    "event": "embedding.job_completed",
                    "context": {
                        "job_id": job_id,
                        "succeeded": succeeded,
                        "total": processed,
                    },
                },
            )
        else:
            _log.error(
                f"embedding job failed: {job_id}",
                extra={
                    "event": "embedding.job_failed",
                    "context": {
                        "job_id": job_id,
                        "succeeded": succeeded,
                        "failed": failed,
                        "total": processed,
                    },
                },
            )
        return failed > 0
