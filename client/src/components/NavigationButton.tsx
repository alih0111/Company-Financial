import { useNavigate, useLocation } from "react-router-dom";

const NavigationButton = () => {
  const navigate = useNavigate();
  const location = useLocation();

  const isOnTablePage = location.pathname === "/Table";

  const searchParams = new URLSearchParams(location.search);
  const companyName = searchParams.get("companyname");

  const handleClick = () => {
    if (isOnTablePage) {
      navigate(`/?companyname=${encodeURIComponent(companyName || "")}`);
    } else {
      navigate(`/Table?companyname=${encodeURIComponent(companyName || "")}`);
    }
  };

  return (
    <button
      onClick={handleClick}
      className="rounded text-sm font-semibold text-gray-800 dark:text-gray-200"
    >
      {isOnTablePage ? "Home" : "Table"}
    </button>
  );
};

export default NavigationButton;
