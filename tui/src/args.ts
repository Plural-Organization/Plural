const DASHES = /^[‐-―−]+(?=[A-Za-z])/;

export function fixDashes(args: string[]): string[] {
  return args.map((arg) => {
    const match = DASHES.exec(arg);
    if (match === null) {
      return arg;
    }
    const rest = arg.slice(match[0].length);
    return `${rest.length > 1 ? "--" : "-"}${rest}`;
  });
}
