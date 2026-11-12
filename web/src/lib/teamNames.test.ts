import { expect, test } from "vitest";
import type { TeamProfile } from "@plural/client";
import { mergeTeams, type Team } from "./team";
import { memberNameProblem, suggestedName, teamNameProblem } from "./teamNames";

test("a member name is what the relay accepts", () => {
  expect(memberNameProblem("alia")).toBeNull();
  expect(memberNameProblem("a.b-c_1")).toBeNull();
  expect(memberNameProblem("-alia")).not.toBeNull();
  expect(memberNameProblem("x".repeat(33))).not.toBeNull();
  expect(memberNameProblem("has space")).not.toBeNull();
});

test("a team name is 1 to 60 characters", () => {
  expect(teamNameProblem("Backend")).toBeNull();
  expect(teamNameProblem("   ")).not.toBeNull();
  expect(teamNameProblem("x".repeat(61))).not.toBeNull();
});

test("the email suggests a name only when it makes a valid one", () => {
  expect(suggestedName("frichaplay@gmail.com")).toBe("frichaplay");
  expect(suggestedName("ann+work@x.io")).toBe("annwork");
  expect(suggestedName("..@x.io")).toBe("");
  expect(suggestedName(null)).toBe("");
});

const team = (id: string, name: string, certificate = "old"): Team => ({
  profile: { relay: "wss://relay.example", team_id: id, team_name: name, team_key: "K", certificate, member: { id: "m", name: "vlad", role: "member" } } as TeamProfile,
  key: {} as CryptoKeyPair,
});

test("teams from the relay replace what was stored, and the list stays in name order", () => {
  const merged = mergeTeams([team("t_2", "Zeta"), team("t_1", "Alpha")], [team("t_2", "Zeta", "fresh"), team("t_3", "Mid")]);
  expect(merged.map((item) => [item.profile.team_name, item.profile.certificate])).toEqual([
    ["Alpha", "old"],
    ["Mid", "old"],
    ["Zeta", "fresh"],
  ]);
});
