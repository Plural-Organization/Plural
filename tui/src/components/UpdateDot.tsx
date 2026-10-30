import { useEffect, useState } from "react";
import { theme } from "../theme";

const PULSE_MS = 900;

export function UpdateDot() {
  const [lit, setLit] = useState(true);
  useEffect(() => {
    const timer = setInterval(() => setLit((value) => !value), PULSE_MS);
    return () => clearInterval(timer);
  }, []);
  return <span fg={lit ? theme.info : theme.accent}>●</span>;
}
