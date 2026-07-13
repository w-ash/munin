"""The roster coverage engine: recall, saturation, per-field verification."""

from vault_scripts.research import coverage
from vault_scripts.research.coverage import Attribute, Entity, FieldObservation


def _grid() -> tuple[list[Entity], list[Attribute], list[FieldObservation]]:
    entities = [
        Entity(
            "E1",
            "Ada",
            in_frame=True,
            fields={"role": "CTO", "email": "a@x"},
            first_pass=1,
        ),
        Entity(
            "E2", "Ben", in_frame=True, fields={"role": "VP", "email": ""}, first_pass=2
        ),
        Entity(
            "E3", "Zed", in_frame=False, fields={"role": "", "email": ""}, first_pass=0
        ),
    ]
    attributes = [Attribute("role", "Role", required=True), Attribute("email", "Email")]
    observations = [
        FieldObservation("E1--role", "V1", 1, "https://a/1"),
        FieldObservation("E1--email", "V2", 1, "https://a/2"),
        FieldObservation("E2--role", "V3", 2, "https://b/3"),
    ]
    return entities, attributes, observations


def test_recall_uses_declared_count() -> None:
    entities, attributes, obs = _grid()
    cells = coverage.field_cells(entities, attributes, obs, frozenset())
    rep = coverage.coverage(entities, attributes, cells, expected_count=4)
    assert rep.found == 2  # only in-frame entities
    assert rep.recall == 0.5
    assert rep.expected == 4


def test_recall_none_without_count_reads_saturation() -> None:
    entities, attributes, obs = _grid()
    cells = coverage.field_cells(entities, attributes, obs, frozenset())
    rep = coverage.coverage(entities, attributes, cells, expected_count=None)
    assert rep.recall is None


def test_undiscovered_in_frame_entity_is_not_a_phantom_pass_zero() -> None:
    # A hand-seeded in-frame entity with no dated observation (first_pass 0)
    # must not appear as a "pass 0" point on the discovery curve.
    entities = [
        Entity("E1", "Ada", in_frame=True, fields={"role": "CTO"}, first_pass=1),
        Entity("E2", "Ben", in_frame=True, fields={"role": ""}, first_pass=0),
    ]
    attributes = [Attribute("role", "Role", required=True)]
    cells = coverage.field_cells(entities, attributes, [], frozenset())
    rep = coverage.coverage(entities, attributes, cells, expected_count=None)
    assert rep.saturating == [(1, 1)]  # no (0, 1) bucket


def test_field_fill_and_verified_rates() -> None:
    entities, attributes, obs = _grid()
    # Only E1's role citation verified; E1 email and E2 role unverified.
    cells = coverage.field_cells(entities, attributes, obs, frozenset({"V1"}))
    rep = coverage.coverage(entities, attributes, cells, expected_count=4)
    # In-frame cells: 2 entities x 2 attrs = 4; filled = E1.role, E1.email, E2.role.
    assert rep.field_fill == 0.75
    assert rep.field_verified == round(1 / 3, 4)
    role = next(a for a in rep.per_attribute if a.attribute_id == "role")
    assert (role.fill_rate, role.n_filled, role.n_verified) == (1.0, 2, 1)


def test_thin_entities_flag_missing_required_field() -> None:
    entities, attributes, obs = _grid()
    entities[1] = Entity("E2", "Ben", in_frame=True, fields={"role": "", "email": ""})
    cells = coverage.field_cells(entities, attributes, obs, frozenset())
    rep = coverage.coverage(entities, attributes, cells, expected_count=4)
    assert rep.thin_entities == ["E2"]  # required 'role' unfilled


def test_out_of_frame_never_inflates_coverage() -> None:
    entities, attributes, obs = _grid()
    cells = coverage.field_cells(entities, attributes, obs, frozenset())
    rep = coverage.coverage(entities, attributes, cells, expected_count=4)
    # E3 is out of frame: excluded from found, fill, and thin.
    assert "E3" not in rep.thin_entities
    assert rep.found == 2


def test_coverage_is_order_independent() -> None:
    entities, attributes, obs = _grid()
    forward = coverage.coverage(
        entities,
        attributes,
        coverage.field_cells(entities, attributes, obs, frozenset({"V1"})),
        expected_count=4,
    )
    backward = coverage.coverage(
        list(reversed(entities)),
        attributes,
        coverage.field_cells(
            list(reversed(entities)), attributes, list(reversed(obs)), frozenset({"V1"})
        ),
        expected_count=4,
    )
    assert forward.field_fill == backward.field_fill
    assert forward.field_verified == backward.field_verified
    assert forward.found == backward.found
