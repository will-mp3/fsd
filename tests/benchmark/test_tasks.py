import json
from dataclasses import replace

import pytest
from pydantic import ValidationError

from fsd.benchmark import contracts, tasks
from fsd.benchmark.contracts import BenchmarkError
from fsd.benchmark.tasks import task_for


def test_textedit_fixture_and_prompt_are_versioned() -> None:
  task = task_for("textedit-edit-save")

  assert task.version == 1
  assert task.app_id == "com.apple.TextEdit"
  assert task.initial_files == (("note.txt", b"Status: draft\nOwner: Alex\n"),)
  assert task.prompt == (
    "In the open TextEdit document, change 'Status: draft' to 'Status: ready'. "
    "Preserve all other text and save the document."
  )
  assert task.final_files == (("note.txt", b"Status: ready\nOwner: Alex\n"),)


@pytest.mark.parametrize(
  ("task_id", "initial_path", "final_path", "directories", "prompt"),
  [
    (
      "finder-rename",
      "draft.txt",
      "final.txt",
      (),
      "In the current Finder folder, rename draft.txt to final.txt. "
      "Keep the file contents unchanged.",
    ),
    (
      "finder-move",
      "report.txt",
      "Archive/report.txt",
      ("Archive",),
      "Move report.txt into the Archive folder in the current Finder folder. "
      "Keep the file name and contents unchanged.",
    ),
  ],
  ids=("rename", "move"),
)
def test_finder_tasks_preserve_contents_and_require_original_path_absent(
  task_id: str,
  initial_path: str,
  final_path: str,
  directories: tuple[str, ...],
  prompt: str,
) -> None:
  task = task_for(task_id)

  assert task.task_id == task_id
  assert task.version == 1
  assert task.app_id == "com.apple.finder"
  assert task.prompt == prompt
  assert task.initial_files == ((initial_path, b"Benchmark fixture.\n"),)
  assert task.directories == directories
  assert task.final_files == ((final_path, b"Benchmark fixture.\n"),)
  assert task.absent_after == (initial_path,)


def test_unknown_task_lists_supported_ids() -> None:
  with pytest.raises(BenchmarkError) as caught:
    task_for("not-a-task")

  message = str(caught.value)
  assert "not-a-task" in message
  assert "Supported tasks:" in message
  for task_id in ("textedit-edit-save", "finder-rename", "finder-move"):
    assert task_id in message


def test_task_manifest_records_identity_and_initial_file_fingerprint() -> None:
  task = task_for("textedit-edit-save")
  manifest = tasks.task_manifest(task)

  assert manifest.schema_version == 1
  assert manifest.task_id == task.task_id
  assert manifest.task_version == task.version
  assert manifest.prompt == task.prompt
  assert manifest.app_id == task.app_id
  assert manifest.setup_protocol == 1
  assert manifest.directories == task.directories
  assert manifest.initial_sha256 == {
    "note.txt": "e66d1758315c7cb232a366788ccd04f368112b47806e79cdda50bf56b905a93a"
  }


@pytest.mark.parametrize("task_id", ["textedit-edit-save", "finder-rename", "finder-move"])
def test_task_manifest_survives_json_round_trip(task_id: str) -> None:
  manifest = tasks.task_manifest(task_for(task_id))

  restored = contracts.TaskManifest.model_validate_json(manifest.model_dump_json())

  assert restored == manifest
  assert restored.directories == task_for(task_id).directories


def test_manifest_fingerprint_tracks_fixture_bytes_without_mutating_task() -> None:
  original = task_for("textedit-edit-save")
  changed = replace(original, initial_files=(("note.txt", b"Different starting text\n"),))

  before = tasks.task_manifest(original)
  after = tasks.task_manifest(changed)

  assert before.initial_sha256["note.txt"] != after.initial_sha256["note.txt"]
  assert tasks.task_manifest(original) == before
  assert original.initial_files == (("note.txt", b"Status: draft\nOwner: Alex\n"),)


@pytest.mark.parametrize(
  ("field", "value"),
  [
    ("schema_version", 2),
    ("schema_version", True),
    ("task_version", 0),
    ("task_version", True),
    ("task_version", "1"),
    ("setup_protocol", 2),
    ("setup_protocol", True),
    ("unexpected", "extra data"),
  ],
  ids=(
    "unknown-schema",
    "boolean-schema",
    "zero-task-version",
    "boolean-task-version",
    "string-task-version",
    "unknown-setup-protocol",
    "boolean-setup-protocol",
    "unknown-field",
  ),
)
def test_task_manifest_rejects_invalid_saved_data(field: str, value: object) -> None:
  data = tasks.task_manifest(task_for("textedit-edit-save")).model_dump(mode="json")
  data[field] = value

  with pytest.raises(ValidationError) as caught:
    contracts.TaskManifest.model_validate_json(json.dumps(data))

  assert any(error["loc"] == (field,) for error in caught.value.errors())
