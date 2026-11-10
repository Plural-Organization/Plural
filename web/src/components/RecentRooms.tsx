import { Button, Description, Label, ListBox, Modal, type Key } from "@heroui/react";
import { ClockCounterClockwise } from "@phosphor-icons/react";
import { useState } from "react";
import { hostOf } from "../lib/links";
import { type SavedRoom } from "../lib/saved";
import { PersonAvatar } from "./PersonAvatar";

interface RecentRoomsProps {
  rooms: SavedRoom[];
  onReopen: (room: SavedRoom) => void;
  onForget: () => void;
}

// The rooms this browser was in, behind one quiet button so the join page stays one screen tall.
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
  return (
    <>
      <Button variant="ghost" size="sm" className="mx-auto mt-5 flex" onPress={() => setOpen(true)}>
        <ClockCounterClockwise size={16} />
        Rooms you were in
        <span className="text-muted">{rooms.length}</span>
      </Button>
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
