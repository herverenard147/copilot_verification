import { useEffect, useState } from "react";

let listener = null;

export function toast(msg) {
  if (listener) listener(msg);
}

export function Toast() {
  const [msg, setMsg] = useState(null);
  const [show, setShow] = useState(false);

  useEffect(() => {
    listener = (m) => {
      setMsg(m);
      setShow(true);
      const t = setTimeout(() => setShow(false), 2600);
      return () => clearTimeout(t);
    };
    return () => { listener = null; };
  }, []);

  return <div className={`toast${show ? " show" : ""}`}>{msg}</div>;
}
