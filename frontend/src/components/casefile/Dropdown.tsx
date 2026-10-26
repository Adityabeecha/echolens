import { KeyboardEvent, ReactNode, useEffect, useId, useRef, useState } from "react";

export interface DropdownOption<T extends string> {
  value: T;
  label: string;
  /** A muted second line, e.g. "Demo" or "health 73/100". */
  hint?: string;
  /** A small coloured dot before the label (health). CSS colour value. */
  dot?: string;
}

/**
 * The case-file dropdown: replaces the browser's native <select>, whose list
 * opened in the operating system's own style (a blue Windows/Android picker)
 * and never matched the rest of the product.
 *
 * Works as a listbox (choose a value) or, with `menu`, as a list of actions.
 * Keyboard: Enter/Space/ArrowDown open; arrows, Home and End move; Enter
 * picks; Escape or Tab closes. A click outside closes it.
 */
export function Dropdown<T extends string>({
  label, options, value, onChange, placeholder = "Choose…", menu = false, align = "start",
  footer, className = "", buttonClassName = "", renderButton, disabled = false, block = false, title,
}: {
  /** Accessible name, e.g. "Product" or "Sort". */
  label: string;
  options: DropdownOption<T>[];
  value?: T | null;
  onChange: (value: T) => void;
  placeholder?: string;
  /** Actions rather than a current value: no checkmark, no aria-selected. */
  menu?: boolean;
  align?: "start" | "end";
  /** Extra content under the options, e.g. an "Add a product" action. */
  footer?: (close: () => void) => ReactNode;
  className?: string;
  buttonClassName?: string;
  /** Custom button content; defaults to the chosen option's label. */
  renderButton?: (chosen: DropdownOption<T> | undefined) => ReactNode;
  disabled?: boolean;
  /** Full width, for form fields. */
  block?: boolean;
  title?: string;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const listRef = useRef<HTMLUListElement | null>(null);
  const chosen = options.find((o) => o.value === value);

  const close = (focusButton = true) => {
    setOpen(false);
    if (focusButton) buttonRef.current?.focus();
  };
  const openAt = (index: number) => {
    setActive(Math.max(0, Math.min(options.length - 1, index)));
    setOpen(true);
  };
  const pick = (option: DropdownOption<T>) => {
    close();
    onChange(option.value);
  };

  useEffect(() => {
    if (!open) return;
    listRef.current?.focus();
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    listRef.current?.querySelector<HTMLElement>(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [open, active]);

  const onButtonKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const at = Math.max(0, options.findIndex((o) => o.value === value));
      openAt(e.key === "ArrowUp" ? at - 1 : at);
    }
  };
  const onListKey = (e: KeyboardEvent<HTMLUListElement>) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((i) => Math.min(options.length - 1, i + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => Math.max(0, i - 1)); }
    else if (e.key === "Home") { e.preventDefault(); setActive(0); }
    else if (e.key === "End") { e.preventDefault(); setActive(options.length - 1); }
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); if (options[active]) pick(options[active]); }
    else if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === "Tab") { setOpen(false); }
  };

  return (
    <div ref={rootRef} className={`cf-dropdown${block ? " cf-dropdown--block" : ""} ${className}`}>
      <button ref={buttonRef} type="button" className={`cf-dropdown__button ${buttonClassName}`}
        disabled={disabled} title={title}
        aria-haspopup={menu ? "menu" : "listbox"} aria-expanded={open} aria-controls={open ? `${id}-list` : undefined}
        aria-label={menu ? label : `${label}: ${chosen?.label ?? placeholder}`}
        onClick={() => (open ? close(false) : openAt(Math.max(0, options.findIndex((o) => o.value === value))))}
        onKeyDown={onButtonKey}>
        {renderButton ? renderButton(chosen) : <>
          {chosen?.dot && <span className="cf-dropdown__dot" style={{ background: chosen.dot }} aria-hidden="true" />}
          <span className="cf-dropdown__value">{chosen?.label ?? placeholder}</span>
        </>}
        <span className="cf-dropdown__caret" aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className={`cf-dropdown__pop cf-dropdown__pop--${align}`}>
          <ul ref={listRef} id={`${id}-list`} role={menu ? "menu" : "listbox"} aria-label={label} tabIndex={-1}
            aria-activedescendant={options[active] ? `${id}-opt-${active}` : undefined} onKeyDown={onListKey}>
            {options.map((o, i) => {
              const selected = !menu && o.value === value;
              return (
                <li key={o.value} id={`${id}-opt-${i}`} data-index={i}
                  role={menu ? "menuitem" : "option"} aria-selected={menu ? undefined : selected}
                  className={`cf-dropdown__opt${i === active ? " is-active" : ""}${selected ? " is-selected" : ""}`}
                  onMouseEnter={() => setActive(i)} onClick={() => pick(o)}>
                  {o.dot && <span className="cf-dropdown__dot" style={{ background: o.dot }} aria-hidden="true" />}
                  <span className="cf-dropdown__label">
                    <span>{o.label}</span>
                    {o.hint && <span className="cf-dropdown__hint">{o.hint}</span>}
                  </span>
                  {selected && <span className="cf-dropdown__check" aria-hidden="true">✓</span>}
                </li>
              );
            })}
          </ul>
          {footer && <div className="cf-dropdown__footer">{footer(() => close(false))}</div>}
        </div>
      )}
    </div>
  );
}
