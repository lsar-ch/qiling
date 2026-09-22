import { STATE_LABEL_ZH } from "./state";

export function stateLabelForHome(state: string): string {
  return STATE_LABEL_ZH[state as keyof typeof STATE_LABEL_ZH] ?? state;
}
