import { Button, Chip, Dropdown, Label } from "@heroui/react";
import { DotsThree, Link as LinkIcon, UserPlus } from "@phosphor-icons/react";
import { label, type Command, type Participant, type Projection } from "@plural/client";
import { cx } from "../../lib/cx";
import { PersonAvatar } from "../PersonAvatar";
import { Section } from "./Section";
import styles from "./Sidebar.module.css";

interface PeopleProps {
  projection: Projection;
  isHost: boolean;
  send: (command: Command) => void;
  onInvite: (role: "participant" | "viewer") => void;
}

function order(a: Participant, b: Participant): number {
  return Number(b.role === "host") - Number(a.role === "host") || Number(b.connected) - Number(a.connected) || a.name.localeCompare(b.name);
}

export function People({ projection, isHost, send, onInvite }: PeopleProps) {
  const state = projection.state;
  return (
    <Section title="in the room">
      <ul className={styles.people}>
        {Object.values(state.participants)
          .sort(order)
          .map((person) => {
            const typing = projection.typing.has(person.id) && person.id !== projection.meId;
            return (
              <li key={person.id} className={cx(styles.person, !person.connected && styles.away)}>
                <PersonAvatar seed={person.id} />
                <span className={styles.name}>
                  {label(state, person)}
                  {person.id === projection.meId ? <span className="muted"> (you)</span> : null}
                </span>
                {typing ? (
                  <span className={styles.typing}>typing…</span>
                ) : person.role === "host" ? (
                  <Chip size="sm" variant="soft" color="accent">
                    <Chip.Label>Host</Chip.Label>
                  </Chip>
                ) : (
                  <span className={cx(styles.role, "cap")}>{person.role}</span>
                )}
                {isHost && person.role !== "host" ? (
                  <Dropdown>
                    <Button isIconOnly size="sm" variant="ghost" aria-label={`Manage ${person.name}`}>
                      <DotsThree size={18} weight="bold" />
                    </Button>
                    <Dropdown.Popover>
                      <Dropdown.Menu
                        onAction={(key) =>
                          send(
                            key === "remove"
                              ? { type: "participant.revoke", participant_id: person.id }
                              : { type: "participant.set_role", participant_id: person.id, role: person.role === "viewer" ? "participant" : "viewer" },
                          )
                        }
                      >
                        <Dropdown.Item id="role" textValue="Change role">
                          <Label>{person.role === "viewer" ? "Let them prompt" : "Make a viewer"}</Label>
                        </Dropdown.Item>
                        <Dropdown.Item id="remove" textValue="Remove" variant="danger">
                          <Label>Remove from the room</Label>
                        </Dropdown.Item>
                      </Dropdown.Menu>
                    </Dropdown.Popover>
                  </Dropdown>
                ) : null}
              </li>
            );
          })}
      </ul>
      {isHost ? (
        <div className={styles.actions}>
          <Button size="sm" variant="tertiary" onPress={() => onInvite("participant")}>
            <LinkIcon size={15} />
            Room link
          </Button>
          <Button size="sm" variant="ghost" onPress={() => onInvite("viewer")}>
            <UserPlus size={15} />
            Viewer invite
          </Button>
        </div>
      ) : null}
    </Section>
  );
}
