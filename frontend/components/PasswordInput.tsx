"use client";

import { useState, type InputHTMLAttributes } from "react";
import { IconEye, IconEyeOff } from "@/components/Icons";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "type">;

/** A password field with a button to show or hide what's typed. */
export function PasswordInput({ className, ...props }: Props) {
  const [visible, setVisible] = useState(false);
  return (
    <span className="password-input">
      <input
        {...props}
        type={visible ? "text" : "password"}
        className={`input${className ? ` ${className}` : ""}`}
        autoCapitalize="none"
        autoCorrect="off"
        spellCheck={false}
      />
      <button
        type="button"
        className="password-toggle"
        onClick={() => setVisible((v) => !v)}
        aria-label={visible ? "Hide password" : "Show password"}
        aria-pressed={visible}
        title={visible ? "Hide password" : "Show password"}
      >
        {visible ? <IconEyeOff size={17} /> : <IconEye size={17} />}
      </button>
    </span>
  );
}
