import { setPresets } from "../src/presets";
import { TEST_CATALOG } from "./support/catalog";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = false;

setPresets(TEST_CATALOG);
