import { createBrowserRouter } from "react-router";
import { Layout } from "./components/Layout";
import { Home } from "./pages/Home";
import { History } from "./pages/History";
import { Settings } from "./pages/Settings";
import { Analyzer } from "./pages/Analyzer";
import { Results } from "./pages/Results";

export const router = createBrowserRouter([
  {
    path: "/",
    Component: Layout,
    children: [
      {
        path: "",
        Component: Home,
      },
      {
        path: "analyzer",
        Component: Analyzer,
      },
      {
        path: "history",
        Component: History,
      },
      {
        path: "settings",
        Component: Settings,
      },
    ],
  },
  {
    path: "/results",
    Component: Results,
  },
]);
