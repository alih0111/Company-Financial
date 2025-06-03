import { useNavigate, useLocation } from "react-router-dom";

const NavigationButton = () => {
  const navigate = useNavigate();
  const location = useLocation();

  const isOnTablePage = location.pathname === "/Table";

  const handleClick = () => {
    if (isOnTablePage) {
      navigate("/"); // Go back home
    } else {
      navigate("/Table"); // Go to table page
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
