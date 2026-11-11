// What a member may be called: what teammates see and @name uses (protocol/team.py NAME_PATTERN).
export const MEMBER_NAME = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$/;

export function memberNameProblem(name: string): string | null {
  return MEMBER_NAME.test(name.trim()) ? null : "Use 1 to 32 letters, digits, dots, dashes or underscores, starting with a letter or digit.";
}

export function teamNameProblem(name: string): string | null {
  const text = name.trim();
  return text.length >= 1 && text.length <= 60 ? null : "A team name is 1 to 60 characters.";
}

// A name to start from: the part of the account's email before the @, made into a valid member name.
export function suggestedName(email: string | null | undefined): string {
  const local = (email ?? "").split("@")[0] ?? "";
  const cleaned = local.replace(/[^A-Za-z0-9_.-]/g, "").replace(/^[^A-Za-z0-9]+/, "").slice(0, 32);
  return MEMBER_NAME.test(cleaned) ? cleaned : "";
}
