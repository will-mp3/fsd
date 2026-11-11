from fsd.benchmark import contracts


def test_measurements_preserve_unknown_cost_and_reported_zero_in_json() -> None:
  unknown = contracts.Measurements.model_validate({"duration_seconds": 1.5})
  reported_zero = contracts.Measurements.model_validate(
    {"duration_seconds": 1.5, "reported_cost": 0.0, "cost_measurements": 1}
  )

  restored_unknown = contracts.Measurements.model_validate_json(unknown.model_dump_json())
  restored_zero = contracts.Measurements.model_validate_json(reported_zero.model_dump_json())

  assert restored_unknown.reported_cost is None
  assert restored_unknown.cost_measurements == 0
  assert restored_zero.reported_cost == 0.0
  assert restored_zero.cost_measurements == 1
