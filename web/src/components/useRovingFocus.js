import { useCallback, useEffect, useRef, useState } from 'react'

// Roving tabindex over a list.
//
// Issue #88 part 2 asks for keyboard navigation through the Research Queue
// "properly rather than bolting on key handlers". The distinction that makes
// it proper is this one: a list of N focusable rows puts N stops in the tab
// order, so reaching the content after the worklist means tabbing past every
// open question. A roving tabindex puts ONE stop there — Tab enters the list
// and Tab leaves it — and the arrow keys move within.
//
// Exactly one item carries tabIndex=0 at a time; the rest carry -1, which
// keeps them programmatically focusable but out of the tab sequence. This is
// the pattern the ARIA authoring practices specify for exactly this shape,
// and it is why the hook owns focus() rather than leaving it to the caller:
// moving the active index without moving real DOM focus would announce
// nothing to a screen reader.
export default function useRovingFocus(count) {
  const [activeIndex, setActiveIndex] = useState(0)
  const refs = useRef([])
  // Only steal focus when the move came from a keypress. Re-rendering the
  // list (a filter changing, data reloading) must not yank focus out of
  // whatever the user was typing in.
  const shouldFocus = useRef(false)

  // A list that shrinks — a question answered, a filter applied — must not
  // leave the active index pointing past the end, or the arrow keys stop
  // responding until the user clicks something.
  useEffect(() => {
    if (count > 0 && activeIndex > count - 1) setActiveIndex(count - 1)
  }, [count, activeIndex])

  useEffect(() => {
    if (!shouldFocus.current) return
    shouldFocus.current = false
    refs.current[activeIndex]?.focus()
  }, [activeIndex])

  const setRef = useCallback((index) => (node) => {
    refs.current[index] = node
  }, [])

  const moveTo = useCallback(
    (index) => {
      if (count === 0) return
      const clamped = Math.max(0, Math.min(index, count - 1))
      shouldFocus.current = true
      setActiveIndex(clamped)
    },
    [count],
  )

  // Returns true when it handled the key, so the caller knows whether to
  // preventDefault. Arrow keys scroll the page otherwise, which fights the
  // focus move the user just asked for.
  const onNavigationKey = useCallback(
    (event) => {
      switch (event.key) {
        case 'ArrowDown':
        case 'j':
          moveTo(activeIndex + 1)
          return true
        case 'ArrowUp':
        case 'k':
          moveTo(activeIndex - 1)
          return true
        case 'Home':
          moveTo(0)
          return true
        case 'End':
          moveTo(count - 1)
          return true
        default:
          return false
      }
    },
    [activeIndex, count, moveTo],
  )

  // Focus without changing which item is active — used to come back from a
  // reason field to the question it belonged to.
  const refocusActive = useCallback(() => {
    refs.current[activeIndex]?.focus()
  }, [activeIndex])

  const itemProps = useCallback(
    (index) => ({
      ref: setRef(index),
      tabIndex: index === activeIndex ? 0 : -1,
      'data-active': index === activeIndex ? 'true' : undefined,
    }),
    [activeIndex, setRef],
  )

  return { activeIndex, moveTo, onNavigationKey, itemProps, refocusActive }
}
