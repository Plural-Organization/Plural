import { Button, Description, Label, ListBox, Modal, type Key } from "@heroui/react";
import { ArrowRight, ClockCounterClockwise } from "@phosphor-icons/react";
import { useState } from "react";
import { hostOf } from "../lib/links";
import { type SavedRoom } from "../lib/saved";
import { PersonAvatar } from "./PersonAvatar";

interface RecentRoomsProps {
  rooms: SavedRoom[];
  onReopen: (room: SavedRoom) => void;
  onForget: () => void;
}

// How many of the rooms this browser was in show on the page; the rest are one click away.
const SHOWN = 3;

function RoomRow({ room, onPress }: { room: SavedRoom; onPress: () => void }) {
  return (
    <button type="button" onClick={onPress} className="pl-row">
      <PersonAvatar seed={room.room} size="sm" />
      <span className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2.5 gap-y-px">
        <span className="font-mono text-sm font-medium tracking-[-0.01em]">{room.room}</span>
        <span className="text-[13px] text-muted">
          as {room.name} on <span className="font-mono text-[12.5px]">{hostOf(room.url)}</span>
        </span>
      </span>
      <ArrowRight size={16} aria-hidden="true" className="shrink-0 text-muted" />
    </button>
  );
}

// The rooms this browser was in, newest first, right under the form so they are seen.
export function RecentRooms({ rooms, onReopen, onForget }: RecentRoomsProps) {
  const [open, setOpen] = useState(false);
  if (rooms.length === 0) {
    return null;
  }
  const reopen = (key: Key) => {
    const room = rooms.find((item) => item.room === key);
    if (room !== undefined) {
      setOpen(false);
      onReopen(room);
    }
  };
  const newest = [...rooms].sort((a, b) => b.savedAt - a.savedAt);
  return (
    <>
      <section aria-labelledby="pl-recent" className="pl-in flex flex-col gap-0.5" style={{ animationDelay: "140ms" }}>
        <div className="flex items-center justify-between gap-2 pr-1 pl-3">
          <h2 id="pl-recent" className="m-0 font-sans text-[13px] font-medium text-muted">Rooms you were in</h2>
          <div className="flex gap-0.5">
            {rooms.length > SHOWN ? (
              <button type="button" className="pl-quiet-button text-foreground" onClick={() => setOpen(true)}>
                All {rooms.length}
              </button>
            ) : null}
            <button type="button" className="pl-quiet-button" onClick={() => setOpen(true)}>
              Manage
            </button>
          </div>
        </div>
        <div className="flex flex-col gap-0.5 rounded-[22px] border border-border bg-white/[0.02] p-1">
          {newest.slice(0, SHOWN).map((room) => (
            <RoomRow key={room.room} room={room} onPress={() => onReopen(room)} />
          ))}
        </div>
      </section>
      <Modal.Backdrop isOpen={open} onOpenChange={setOpen}>
        <Modal.Container scroll="inside">
          <Modal.Dialog className="sm:max-w-[30rem]">
            <Modal.CloseTrigger />
            <Modal.Header>
              <Modal.Heading className="font-display text-2xl font-medium tracking-[-0.02em]">Rooms you were in</Modal.Heading>
            </Modal.Header>
            <Modal.Body>
              <ListBox aria-label="Rooms you were in" selectionMode="none" onAction={reopen}>
                {rooms.map((room) => (
                  <ListBox.Item key={room.room} id={room.room} textValue={room.room}>
                    <PersonAvatar seed={room.room} />
                    <div className="flex min-w-0 flex-col">
                      <Label className="truncate font-mono text-[13px]">{room.room}</Label>
                      <Description className="truncate">as {room.name} on {hostOf(room.url)}</Description>
                    </div>
                  </ListBox.Item>
                ))}
              </ListBox>
            </Modal.Body>
            <Modal.Footer>
              <Button
                variant="ghost"
                onPress={() => {
                  onForget();
                  setOpen(false);
                }}
              >
                Forget these rooms
              </Button>
              <Button slot="close">Done</Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </>
  );
}
