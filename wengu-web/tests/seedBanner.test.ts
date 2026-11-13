import assert from "node:assert/strict";
import test from "node:test";

import { shouldShowSeedBanner } from "../src/setup/seedBanner.ts";

test("seedLoaded=false：显示未装载横幅", () => {
  assert.equal(shouldShowSeedBanner(false), true);
});

test("seedLoaded=true：不显示横幅", () => {
  assert.equal(shouldShowSeedBanner(true), false);
});

test("seedLoaded=null（加载中）：不显示横幅", () => {
  assert.equal(shouldShowSeedBanner(null), false);
});

test("seedLoaded=undefined：不显示横幅", () => {
  assert.equal(shouldShowSeedBanner(undefined), false);
});