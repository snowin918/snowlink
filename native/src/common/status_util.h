#pragma once

#include <string>

namespace snowlink {

inline int32_t hresult_to_status(long hr) noexcept {
    return hr == 0 ? 0 : static_cast<int32_t>(hr);
}

inline std::string make_error_message(const char* prefix, long hr) {
    return std::string(prefix) + " (HRESULT=" + std::to_string(hr) + ")";
}

} // namespace snowlink
