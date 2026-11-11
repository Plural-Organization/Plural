import { Button, Card, Chip, Description, Header, Label, ListBox, Modal, SearchField, type Key } from "@heroui/react";
import { CaretUpDown, Check } from "@phosphor-icons/react";
import { useState } from "react";
import type { Provider } from "../lib/agent";
import { groups, statusOf } from "../lib/agentSetup";
import { AgentLogo } from "./AgentLogo";

function Status({ provider }: { provider: Provider }) {
  const { label, tone } = statusOf(provider);
  return (
    <Chip size="sm" variant="soft" color={tone} className="flex-none">
      <Chip.Label>{label}</Chip.Label>
    </Chip>
  );
}

interface ProviderPickerProps {
  providers: Provider[];
  value: Provider;
  onPick: (id: string) => void;
}

// Which agent runs: the one chosen, in a card, and every provider this computer can use in a window
// with search. Each row says whether it works here yet.
export function ProviderPicker({ providers, value, onPick }: ProviderPickerProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const shown = groups(providers, query);
  const pick = (key: Key) => {
    onPick(String(key));
    setOpen(false);
  };
  return (
    <>
      <Card variant="secondary">
        <Card.Content className="flex-row items-center gap-3">
          <AgentLogo label={value.label} size={22} />
          <div className="min-w-0 flex-1">
            <p className="truncate text-[15px] font-medium">{value.label}</p>
            <Description className="truncate">{value.hint}</Description>
          </div>
          <Status provider={value} />
          <Button size="sm" variant="secondary" onPress={() => setOpen(true)} aria-label="Choose another provider">
            Change
            <CaretUpDown size={14} />
          </Button>
        </Card.Content>
      </Card>
      <Modal.Backdrop
        isOpen={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (!next) setQuery("");
        }}
      >
        <Modal.Container scroll="inside">
          <Modal.Dialog className="sm:max-w-[34rem]">
            <Modal.CloseTrigger />
            <Modal.Header className="gap-3">
              <Modal.Heading className="font-display text-2xl font-medium tracking-[-0.02em]">Choose an agent</Modal.Heading>
              <SearchField fullWidth aria-label="Search providers" value={query} onChange={setQuery}>
                <SearchField.Group>
                  <SearchField.SearchIcon />
                  <SearchField.Input placeholder="Search providers" autoComplete="off" />
                  <SearchField.ClearButton />
                </SearchField.Group>
              </SearchField>
            </Modal.Header>
            <Modal.Body>
              {shown.length === 0 ? (
                <p className="py-6 text-center text-sm text-muted">No provider matches “{query.trim()}”.</p>
              ) : (
                <ListBox aria-label="Providers" selectionMode="none" onAction={pick}>
                  {shown.map((group) => (
                    <ListBox.Section key={group.title}>
                      <Header className="px-2 pb-1 pt-3 text-xs font-medium uppercase tracking-wide text-muted">{group.title}</Header>
                      {group.providers.map((provider) => (
                        <ListBox.Item key={provider.id} id={provider.id} textValue={provider.label}>
                          <AgentLogo label={provider.label} size={20} decorative />
                          <div className="flex min-w-0 flex-1 flex-col">
                            <Label className="flex items-center gap-1.5 truncate">
                              {provider.label}
                              {provider.id === value.id ? <Check size={13} weight="bold" aria-label="Chosen now" className="flex-none text-muted" /> : null}
                            </Label>
                            <Description className="truncate">{provider.hint}</Description>
                          </div>
                          <Status provider={provider} />
                        </ListBox.Item>
                      ))}
                    </ListBox.Section>
                  ))}
                </ListBox>
              )}
            </Modal.Body>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </>
  );
}
