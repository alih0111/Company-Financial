import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { getAuthStatus } from "../hooks/useGetUser";

// محافظت روت: توکن موجود و معتبر (منقضی‌نشده) لازم است
const ProtectedRoute = ({ children }: { children: ReactNode }) => {
  const { username } = getAuthStatus();
  return username ? <>{children}</> : <Navigate to="/login" replace />;
};

export default ProtectedRoute;
