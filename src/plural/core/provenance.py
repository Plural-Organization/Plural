from plural.protocol.models import Origin, Provenance, Role


def direct(initiator_id: str, role: Role) -> Provenance:
    return Provenance(initiator_id=initiator_id, initiator_role=role, origin=Origin.DIRECT)


def from_proposal(author_id: str, role: Role) -> Provenance:
    return Provenance(initiator_id=author_id, initiator_role=role, origin=Origin.PROPOSAL)


def is_guest_originated(provenance: Provenance) -> bool:
    return provenance.origin is Origin.PROPOSAL or provenance.initiator_role is not Role.HOST


def merge(current: Provenance, incoming: Provenance) -> Provenance:
    if is_guest_originated(current) or not is_guest_originated(incoming):
        return current
    return incoming
