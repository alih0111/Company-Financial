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
    <button onClick={handleClick} className=" text-white rounded">
      {isOnTablePage ? "Home" : "Table"}
    </button>
  );
};

export default NavigationButton;
