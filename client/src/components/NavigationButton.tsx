import { useNavigate, useLocation } from "react-router-dom";
import Select from "react-select";
import { useDarkMode } from "../utils/theme";

type PageKey = "Home" | "Table" | "Portfolio";

const pages: { value: PageKey; path: string; label: string }[] = [
  { value: "Home", path: "/", label: "Home" },
  { value: "Table", path: "/Table", label: "Table" },
  { value: "Portfolio", path: "/portfolio", label: "Portfolio" },
];

const NavigationButton = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { darkMode } = useDarkMode();

  const companyName = new URLSearchParams(location.search).get("companyname");

  const activeValue: PageKey =
    pages.find((p) => p.path === location.pathname)?.value || "Home";

  const handleChange = (opt: { value: PageKey; path: string } | null) => {
    if (!opt) return;
    navigate(
      opt.value === "Home"
        ? `/?companyname=${encodeURIComponent(companyName || "")}`
        : `${opt.path}?companyname=${encodeURIComponent(companyName || "")}`
    );
  };

  return (
    <div className="w-28">
      <Select
        value={pages.find((p) => p.value === activeValue) || null}
        onChange={handleChange}
        options={pages}
        isSearchable={false}
        menuPlacement="bottom"
        styles={{
          control: (base, state) => ({
            ...base,
            borderRadius: "0.75rem",
            borderColor: state.isFocused ? "#6366f1" : "#d1d5db",
            boxShadow: state.isFocused ? "0 0 0 2px rgba(99, 102, 241, 0.3)" : "none",
            transition: "all 0.2s",
            minHeight: "2rem",
            backgroundColor: darkMode ? "#1f2937" : "white",
          }),
          singleValue: (base) => ({
            ...base,
            color: darkMode ? "#e5e7eb" : "#1f2937",
            fontWeight: 600,
          }),
          menu: (base) => ({
            ...base,
            borderRadius: "0.75rem",
            boxShadow: "0px 10px 15px -3px rgba(0,0,0,0.1)",
            backgroundColor: darkMode ? "#1f2937" : "white",
            zIndex: 50,
          }),
          option: (base, state) => ({
            ...base,
            backgroundColor: state.isSelected
              ? "#6366f1"
              : state.isFocused
                ? darkMode
                  ? "#374151"
                  : "#eef2ff"
                : "transparent",
            color: state.isSelected ? "white" : darkMode ? "#e5e7eb" : "#1f2937",
            fontWeight: state.isSelected ? 600 : 400,
            cursor: "pointer",
          }),
          dropdownIndicator: (base) => ({ ...base, color: darkMode ? "#9ca3af" : "#6b7280" }),
          indicatorSeparator: () => ({ display: "none" }),
        }}
      />
    </div>
  );
};

export default NavigationButton;