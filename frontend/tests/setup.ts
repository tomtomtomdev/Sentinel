import "@testing-library/jest-dom/vitest";

afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
  // clear (not restore): module-mock implementations set at factory time must
  // survive across tests; only call history is reset.
  vi.clearAllMocks();
});
