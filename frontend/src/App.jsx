import { useEffect, useState } from "react";
import Landing from "./Landing.jsx";
import Dashboard from "./Dashboard.jsx";

function useHashRoute() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const onChange = () => {
      setHash(window.location.hash);
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return hash;
}

export default function App() {
  const hash = useHashRoute();
  const isDashboard = hash.startsWith("#/dashboard");
  return isDashboard ? <Dashboard /> : <Landing />;
}
