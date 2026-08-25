import '@testing-library/jest-dom/vitest'

// jsdom implements no layout, so Element.prototype.scrollIntoView does not
// exist. Any component that keeps a message list pinned to the bottom calls
// it in an effect and throws during render under test. Stubbing it here
// rather than guarding at every call site keeps the guard out of product
// code, where it would read as defensive against something real.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function scrollIntoView() {}
}
