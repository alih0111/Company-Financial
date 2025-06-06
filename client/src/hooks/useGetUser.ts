import { jwtDecode } from "jwt-decode";

interface TokenPayload {
  exp: number;
  isAdmin: boolean;
  username: string; // Make sure this is included in your JWT payload
}

interface AuthStatus {
  isAdmin: boolean;
  username: string | null;
}

export const getAuthStatus = (): AuthStatus => {
  try {
    const token = localStorage.getItem("token");
    if (!token) return { isAdmin: false, username: null };

    const decoded = jwtDecode<TokenPayload>(token);
    const currentTime = Date.now() / 1000;

    if (decoded.exp < currentTime) {
      localStorage.removeItem("token");
      return { isAdmin: false, username: null };
    }

    return {
      isAdmin: decoded.isAdmin,
      username: decoded.username,
    };
  } catch (e) {
    return { isAdmin: false, username: null };
  }
};
