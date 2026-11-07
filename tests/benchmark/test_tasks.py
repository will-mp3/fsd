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
