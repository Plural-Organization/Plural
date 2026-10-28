import { describe, expect, test } from "bun:test";
import { isShareMode, lanAddress, relayProblem, shareLaunch } from "../src/share";

const base = ["--name", "vlad"];

describe("relay address", () => {
  test("accepts wss and ws", () => {
    expect(relayProblem("wss://relay.example.com")).toBeNull();
    expect(relayProblem(" ws://10.0.0.5:8787 ")).toBeNull();
  });

  test("rejects other schemes and text", () => {
    expect(relayProblem("https://relay.example.com")).toContain("wss://");
    expect(relayProblem("relay.example.com")).toContain("not a web address");
    expect(relayProblem("")).toContain("not a web address");
  });
});

describe("lan address", () => {
  test("takes the first external IPv4", () => {
    const interfaces = {
      lo0: [{ family: "IPv4", address: "127.0.0.1", internal: true }],
      en0: [
        { family: "IPv6", address: "fe80::1", internal: false },
        { family: "IPv4", address: "192.168.1.20", internal: false },
      ],
    } as never;
    expect(lanAddress(interfaces)).toBe("192.168.1.20");
  });

  test("is null without a network", () => {
    expect(lanAddress({ lo0: [{ family: "IPv4", address: "127.0.0.1", internal: true }] } as never)).toBeNull();
  });
});

describe("share launch", () => {
  test("local adds nothing", () => {
    expect(shareLaunch({ share: "local", relayUrl: "wss://r.example.com" }, base, 7001, "192.168.1.20")).toEqual({
      args: base,
      note: null,
    });
  });

  test("relay passes the saved address", () => {
    const launch = shareLaunch({ share: "relay", relayUrl: " wss://r.example.com " }, base, 7001, null);
    expect(launch.args).toEqual([...base, "--relay", "wss://r.example.com"]);
    expect(launch.note).toBeNull();
  });

  test("relay without a valid address stays local and says why", () => {
    for (const relayUrl of ["", "nope"]) {
      const launch = shareLaunch({ share: "relay", relayUrl }, base, 7001, null);
      expect(launch.args).toEqual(base);
      expect(launch.note).toContain("sharing over the internet is off");
    }
  });

  test("network binds every interface and advertises the lan address", () => {
    const launch = shareLaunch({ share: "network", relayUrl: "" }, base, 7001, "192.168.1.20");
    expect(launch.args).toEqual([...base, "--bind", "0.0.0.0", "--port", "7001", "--public-url", "ws://192.168.1.20:7001"]);
  });

  test("network without an address stays local and says why", () => {
    const launch = shareLaunch({ share: "network", relayUrl: "" }, base, 7001, null);
    expect(launch.args).toEqual(base);
    expect(launch.note).toContain("no network address");
  });

  test("an explicit address flag wins over the saved choice", () => {
    for (const flag of ["--relay", "--public-url", "--bind"]) {
      const args = [...base, flag, "x"];
      expect(shareLaunch({ share: "network", relayUrl: "wss://r.example.com" }, args, 7001, "10.0.0.2").args).toEqual(args);
    }
  });
});

test("share modes", () => {
  expect(isShareMode("relay")).toBe(true);
  expect(isShareMode("wan")).toBe(false);
});
